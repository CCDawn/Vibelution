from config import LLMProfile, ProviderConfig
from core.llm.adapters import AnthropicAdapter, OpenAICompatibleAdapter


def make_openai_compat_adapter(**profile_overrides):
    profile_values = {
        "profile_id": "primary",
        "provider_id": "default",
        "model": "gpt-5.5",
        "transport": "responses",
    }
    profile_values.update(profile_overrides)
    return OpenAICompatibleAdapter(
        ProviderConfig(provider_id="default", kind="relay", compat_mode="openai"),
        LLMProfile(**profile_values),
    )


def test_no_reasoning_contract_does_not_inject_effort_for_gpt5_name():
    """D2: name heuristics must not inject reasoning without protocol contract."""
    adapter = make_openai_compat_adapter(reasoning_effort="high")

    assert adapter.payload_thinking_parameters() == {}
    assert adapter.reasoning_effort_log_fields()["reasoningEffortAdapter"] == "none"


def test_operator_reasoning_contract_injects_reasoning_object():
    adapter = make_openai_compat_adapter(
        reasoning_effort="high",
        reasoning_effort_values=["low", "high"],
        default_reasoning_effort="low",
        reasoning_effort_adapter="reasoning_object",
        reasoning_effort_map={"high": "high", "low": "low"},
    )

    assert adapter.payload_thinking_parameters() == {"reasoning": {"effort": "high"}}
    fields = adapter.reasoning_effort_log_fields()
    assert fields["reasoningEffortRequested"] == "high"
    assert fields["reasoningEffortEffective"] == "high"
    assert fields["reasoningEffortAdapter"] == "reasoning_object"


def make_anthropic_adapter(**profile_overrides):
    profile_values = {
        "profile_id": "primary",
        "provider_id": "default",
        "model": "claude-3-5-sonnet-20241022",
    }
    profile_values.update(profile_overrides)
    return AnthropicAdapter(
        ProviderConfig(provider_id="default", kind="anthropic"),
        LLMProfile(**profile_values),
    )


def test_opus_4_7_omits_deprecated_sampling_and_keeps_adaptive_thinking():
    adapter = make_anthropic_adapter(
        model="claude-opus-4-7",
        temperature=0.7,
        thinking_type="adaptive",
        thinking_display="summarized",
    )

    assert adapter.payload_sampling_parameters() == {}
    assert adapter.payload_thinking_parameters() == {
        "thinking": {"type": "adaptive", "display": "summarized"}
    }


def test_disabled_thinking_omits_display():
    adapter = make_anthropic_adapter(
        model="claude-opus-4-7",
        thinking_type="disabled",
        thinking_display="summarized",
    )

    assert adapter.payload_thinking_parameters() == {"thinking": {"type": "disabled"}}


def test_older_claude_keeps_temperature():
    adapter = make_anthropic_adapter(temperature=0.2)

    assert adapter.payload_sampling_parameters()["temperature"] == 0.2
