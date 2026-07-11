from config import LLMProfile, ProviderConfig
from core.llm.adapters import AnthropicAdapter


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
