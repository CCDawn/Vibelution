"""Protocol wire registration + vendor cache strategy alignment."""

from __future__ import annotations

from core.llm.payload_builder import (
    PayloadBuildInput,
    PayloadPolicyActions,
    _apply_anthropic_explicit_prompt_cache_markers,
    _apply_explicit_prompt_cache_markers,
    _merge_qwen_consecutive_tool_messages,
    _prompt_cache_provider_strategy,
)
from core.llm.protocols import WireProtocol
from core.llm.wire.registry import build_default_wire_adapter_registry
from tests.helpers.isolated_config import isolated_settings_config


def test_wire_registry_covers_all_declared_wire_protocols():
    registry = build_default_wire_adapter_registry()
    adapter_ids = {
        WireProtocol.ANTHROPIC_MESSAGES: "anthropic_messages_litellm_compat",
    }
    for wire in WireProtocol:
        adapter_id = adapter_ids.get(wire, wire.value)
        adapter = registry.resolve(
            type(
                "R",
                (),
                {
                    "adapter_id": adapter_id,
                    "wire_protocol": wire,
                    "provider_id": "p",
                    "runtime_endpoint": "https://example.test",
                    "model_id": "m",
                },
            )()
        )
        assert adapter.wire_protocol == wire
        assert adapter.adapter_id == adapter_id


def test_anthropic_automatic_strategy_is_top_level_cache_control():
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "anthropic",
            "llm.providers.default.base_url": "https://api.anthropic.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "claude-sonnet-4",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    from core.llm.adapters import get_provider_adapter
    from core.llm.protocol_resolver import resolve_model_protocol
    from core.llm.types import LLMCapabilities

    route = resolve_model_protocol(profile, provider)
    adapter = get_provider_adapter(provider, profile)
    build_input = PayloadBuildInput(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        profile=profile,
        provider=provider,
        adapter=adapter,
        route=route,
        capabilities=LLMCapabilities(supports_prompt_cache=True),
        stream=False,
        api_key="test",
        profile_id="primary",
        config=config,
    )
    strategy = _prompt_cache_provider_strategy(build_input, "automatic")
    assert strategy == "anthropic_automatic_top_level"


def test_anthropic_explicit_markers_land_on_system_block():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="anthropic_explicit_cache_control")
    messages = [
        {"role": "system", "content": "You are a careful assistant."},
        {"role": "user", "content": "hello"},
    ]
    out = _apply_anthropic_explicit_prompt_cache_markers(messages, actions)
    assert actions.anthropic_prompt_cache_markers_added >= 1
    system = out[0]
    assert isinstance(system["content"], list)
    assert any(
        isinstance(block, dict) and block.get("cache_control", {}).get("type") == "ephemeral"
        for block in system["content"]
    )


def test_explicit_dispatcher_routes_qwen_and_anthropic():
    qwen_actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    anthropic_actions = PayloadPolicyActions(prompt_cache_provider_strategy="anthropic_explicit_cache_control")
    messages = [
        {"role": "user", "content": "history"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "now"},
    ]
    qwen_out = _apply_explicit_prompt_cache_markers(messages, qwen_actions)
    anthropic_out = _apply_explicit_prompt_cache_markers(messages, anthropic_actions)
    assert qwen_actions.qwen_prompt_cache_markers_added >= 0
    assert anthropic_actions.anthropic_prompt_cache_markers_added >= 0
    assert isinstance(qwen_out, list)
    assert isinstance(anthropic_out, list)


def test_deepseek_automatic_strategy_unchanged():
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "deepseek",
            "llm.providers.default.base_url": "https://api.deepseek.com",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4-flash",
            "llm.profiles.primary.prompt_cache.mode": "automatic",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    from core.llm.adapters import get_provider_adapter
    from core.llm.protocol_resolver import resolve_model_protocol
    from core.llm.types import LLMCapabilities

    route = resolve_model_protocol(profile, provider)
    adapter = get_provider_adapter(provider, profile)
    build_input = PayloadBuildInput(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        profile=profile,
        provider=provider,
        adapter=adapter,
        route=route,
        capabilities=LLMCapabilities(),
        stream=False,
        api_key="test",
        profile_id="primary",
        config=config,
    )
    assert _prompt_cache_provider_strategy(build_input, "automatic") == "deepseek_automatic"


def _parallel_tool_messages() -> list[dict]:
    return [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                {"id": "call_2", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                {"id": "call_3", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result-1"},
        {"role": "tool", "tool_call_id": "call_2", "content": "result-2"},
        {"role": "tool", "tool_call_id": "call_3", "content": "result-3"},
    ]


def test_qwen_explicit_cache_merges_consecutive_tool_messages_and_marks_tail():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    out = _merge_qwen_consecutive_tool_messages(_parallel_tool_messages(), actions)

    assert actions.qwen_tool_message_runs_merged == 1
    assert actions.qwen_tool_tail_cache_markers_added == 1
    # Non-tool messages keep their shape; the tool run collapses into one message.
    assert [item["role"] for item in out] == ["system", "user", "assistant", "tool"]
    merged = out[-1]
    assert merged.get("role") == "tool"
    assert "tool_call_id" not in merged
    blocks = merged["content"]
    assert [block.get("tool_call_id") for block in blocks] == ["call_1", "call_2", "call_3"]
    assert [block.get("text") for block in blocks] == ["result-1", "result-2", "result-3"]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in block for block in blocks[:-1])


def test_qwen_explicit_cache_keeps_singleton_tool_messages_classic():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    messages = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result-1"},
        {"role": "assistant", "content": "done"},
    ]
    out = _merge_qwen_consecutive_tool_messages(messages, actions)

    assert actions.qwen_tool_message_runs_merged == 0
    assert actions.qwen_tool_tail_cache_markers_added == 0
    assert out[-2] == {"role": "tool", "tool_call_id": "call_1", "content": "result-1"}


def test_qwen_explicit_cache_merges_every_history_tool_run_with_stable_prefix():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    history_run = [
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                {"id": "call_2", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result-1"},
        {"role": "tool", "tool_call_id": "call_2", "content": "result-2"},
    ]
    next_iteration = history_run + [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_3", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_3", "content": "result-3"},
        {"role": "tool", "tool_call_id": "call_4", "content": "result-4"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_5", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
                {"id": "call_6", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "call_5", "content": "result-5"},
        {"role": "tool", "tool_call_id": "call_6", "content": "result-6"},
    ]
    first = _merge_qwen_consecutive_tool_messages(history_run, actions)
    second_actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    second = _merge_qwen_consecutive_tool_messages(next_iteration, second_actions)

    assert actions.qwen_tool_message_runs_merged == 1
    assert second_actions.qwen_tool_message_runs_merged == 3

    def _strip_markers(items: list[dict]) -> list[dict]:
        cleaned: list[dict] = []
        for item in items:
            copied = dict(item)
            if isinstance(copied.get("content"), list):
                copied["content"] = [
                    {key: value for key, value in block.items() if key != "cache_control"}
                    if isinstance(block, dict)
                    else block
                    for block in copied["content"]
                ]
            cleaned.append(copied)
        return cleaned

    # The earlier merged run keeps byte-identical payload content (markers are
    # request-scoped), so the provider prefix match survives across iterations.
    assert _strip_markers(first) == _strip_markers(second[: len(first)])
    assert second[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert second_actions.qwen_tool_tail_cache_markers_added == 1


def test_qwen_tool_merge_disabled_for_responses_transport():
    actions = PayloadPolicyActions(prompt_cache_provider_strategy="qwen_explicit_cache_control")
    out = _apply_explicit_prompt_cache_markers(
        _parallel_tool_messages(),
        actions,
        merge_tool_messages=False,
    )
    assert actions.qwen_tool_message_runs_merged == 0
    assert [item["role"] for item in out] == ["system", "user", "assistant", "tool", "tool", "tool"]
    assert out[-1] == {"role": "tool", "tool_call_id": "call_3", "content": "result-3"}


def test_non_qwen_strategies_leave_tool_messages_unmerged():
    anthropic_actions = PayloadPolicyActions(
        prompt_cache_provider_strategy="anthropic_explicit_cache_control"
    )
    parallel = _parallel_tool_messages()
    out = _apply_explicit_prompt_cache_markers(parallel, anthropic_actions)
    assert anthropic_actions.qwen_tool_message_runs_merged == 0
    tool_messages = [item for item in out if item.get("role") == "tool"]
    assert len(tool_messages) == 3

    disabled_actions = PayloadPolicyActions(prompt_cache_provider_strategy="disabled")
    out_disabled = _apply_explicit_prompt_cache_markers(parallel, disabled_actions)
    assert out_disabled == [dict(item) for item in parallel]


def _dashscope_qwen_explicit_config():
    return isolated_settings_config(
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


def test_dashscope_qwen_explicit_cache_merges_parallel_tool_results_end_to_end():
    from core.llm.client import LLMClient

    def tool_call(call_id: str) -> dict:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": "search_tool", "arguments": "{}"},
        }

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "stable system", "cache_control": {"type": "ephemeral"}}],
        },
        {"role": "user", "content": "检索这个问题"},
        {
            "role": "assistant",
            "content": "我先并行检索三个来源。",
            "tool_calls": [tool_call("call_a"), tool_call("call_b"), tool_call("call_c")],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "结果A"},
        {"role": "tool", "tool_call_id": "call_b", "content": "结果B"},
        {"role": "tool", "tool_call_id": "call_c", "content": "结果C"},
    ]

    client = LLMClient(config=_dashscope_qwen_explicit_config(), backend=lambda payload: payload)
    payload = client._build_payload(messages)

    tool_messages = [message for message in payload["messages"] if message.get("role") == "tool"]
    assert len(tool_messages) == 1
    merged = tool_messages[0]
    assert "tool_call_id" not in merged
    blocks = merged["content"]
    assert [block.get("tool_call_id") for block in blocks] == ["call_a", "call_b", "call_c"]
    assert [block.get("text") for block in blocks] == ["结果A", "结果B", "结果C"]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    summary = client._last_payload_protocol_summary
    assert summary["payloadPolicyQwenToolMessageRunsMerged"] == 1
    assert summary["payloadPolicyQwenToolTailCacheMarkersAdded"] == 1
    # The checkpoint marker still lands on the last assistant message.
    assistant_messages = [message for message in payload["messages"] if message.get("role") == "assistant"]
    assert assistant_messages[-1]["content"] == [
        {"type": "text", "text": "我先并行检索三个来源。", "cache_control": {"type": "ephemeral"}},
    ]


def test_dashscope_qwen_explicit_cache_keeps_single_tool_result_classic_end_to_end():
    from core.llm.client import LLMClient

    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "stable system", "cache_control": {"type": "ephemeral"}}],
        },
        {"role": "user", "content": "检索这个问题"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_a", "type": "function", "function": {"name": "search_tool", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call_a", "content": "结果A"},
    ]

    client = LLMClient(config=_dashscope_qwen_explicit_config(), backend=lambda payload: payload)
    payload = client._build_payload(messages)

    tool_messages = [message for message in payload["messages"] if message.get("role") == "tool"]
    assert tool_messages == [{"role": "tool", "tool_call_id": "call_a", "content": "结果A"}]
    summary = client._last_payload_protocol_summary
    assert summary["payloadPolicyQwenToolMessageRunsMerged"] == 0
    assert summary["payloadPolicyQwenToolTailCacheMarkersAdded"] == 0
