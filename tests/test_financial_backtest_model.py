"""Regression tests for stateless, point-in-time AI backtest decisions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.llm.client as client_mod
from core.llm.client import LLMClient
from core.llm.types import LLMError
from core.web.services.financial_backtest import decision as decision_mod
from core.web.services.financial_backtest.data import BacktestInputError, Candle
from tests.helpers.isolated_config import isolated_settings_config


def _retry_config(*, max_attempts: int = 5):
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://agg.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4.1-flash",
            "llm.profiles.primary.reasoning_effort": "high",
            "llm.profiles.primary.reasoning_effort_values": ["low", "medium", "high"],
            "llm.profiles.primary.reasoning_effort_adapter": "reasoning_effort",
            "llm.profiles.primary.retry_policy.max_attempts": max_attempts,
            "llm.profiles.primary.retry_policy.backoff_base_seconds": 0.1,
            "llm.profiles.primary.streaming": False,
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.tool_calling_mode": "auto",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    provider.__dict__["service_class"] = "aggregator"
    return config


def _decision_config(
    *,
    model_id: str = "test-qwen",
    model: str = "Qwen-Test-32B",
    qwen_protocol: bool = True,
    thinking_type: str = "adaptive",
    reasoning_effort: str = "high",
):
    config = isolated_settings_config(
        **{
            "llm.providers.default.kind": "llamacpp",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "configured-placeholder",
            "llm.profiles.primary.max_output_tokens": 4096,
            "llm.profiles.primary.retry_policy.max_attempts": 5,
            "llm.profiles.primary.reasoning_effort": reasoning_effort,
            "llm.profiles.primary.default_reasoning_effort": reasoning_effort,
            "llm.profiles.primary.reasoning_effort_adapter": "reasoning_effort",
            "llm.profiles.primary.thinking_type": thinking_type,
            "llm.profiles.primary.streaming": False,
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.tool_calling_mode": "auto",
            "llm.profiles.primary.transport": "chat_completions",
        }
    )
    provider_id = config.llm.get_profile("primary").provider_id
    entry = {"provider_id": provider_id, "model": model}
    if qwen_protocol:
        entry.update(
            {
                "protocol": "llamacpp_qwen_thinking",
                "transport": "chat_completions",
                "contract": "tool_chat",
                "thinking_type": "adaptive",
                "capabilities": {
                    "streaming": True,
                    "tools": True,
                    "thinking": True,
                    "reasoningRoundtrip": False,
                },
                "compat": {
                    "requiresStringContent": True,
                    "strictMessageKeys": True,
                    "allowAssistantPrefill": False,
                    "reasoningRoundtrip": False,
                    "thinkingFormat": "qwen",
                    "toolChoiceMode": "omit",
                    "streamUsageOptions": False,
                },
            }
        )
    else:
        entry.update(
            {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "thinking_type": "disabled",
                "reasoning_effort": "",
                "default_reasoning_effort": "",
                "reasoning_effort_adapter": "none",
            }
        )
    config.llm.model_library[model_id] = entry
    return config


@pytest.fixture(autouse=True)
def _isolate_llm_retry_state(monkeypatch):
    monkeypatch.setattr(
        client_mod, "_sleep_with_llm_cancel_check", lambda _seconds: None
    )
    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        client_mod, "_publish_llm_status_event", lambda *args, **kwargs: None
    )
    client_mod._reset_llm_route_unsupported_params_cache()
    yield
    client_mod._reset_llm_route_unsupported_params_cache()


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("provider timeout"),
        Exception(
            "litellm.UnsupportedParamsError: openai does not support parameters: "
            "['reasoning_effort']"
        ),
        Exception("litellm.BadRequestError: pool node rejected the request shape"),
    ],
    ids=["timeout", "unsupported-parameter", "aggregator-bad-request"],
)
def test_backtest_metadata_disables_all_physical_retries(failure):
    calls = []

    def backend(payload):
        calls.append(dict(payload))
        raise failure

    client = LLMClient(config=_retry_config(), backend=backend)
    with pytest.raises(LLMError):
        client.invoke(
            [{"role": "user", "content": "one historical decision"}],
            metadata={"disableAutomaticRetries": True},
        )

    assert len(calls) == 1
    if "UnsupportedParamsError" in str(failure):
        assert "reasoning_effort" in calls[0]


def test_ordinary_llm_call_keeps_profile_retries():
    calls = []

    def backend(payload):
        calls.append(dict(payload))
        if len(calls) == 1:
            raise TimeoutError("temporary provider timeout")
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    response = LLMClient(config=_retry_config(max_attempts=3), backend=backend).invoke(
        [{"role": "user", "content": "ordinary call"}]
    )

    assert response.content == "ok"
    assert len(calls) == 2


def test_runtime_config_for_decision_is_bounded_and_disables_qwen_thinking(monkeypatch):
    config = _decision_config()
    monkeypatch.setattr(decision_mod, "get_config", lambda: config)

    runtime_config = decision_mod.runtime_config_for_decision("test-qwen")
    profile = runtime_config.llm.get_profile("financial_ai_backtest")

    assert runtime_config is not config
    assert profile.max_output_tokens == 512
    assert profile.retry_policy.max_attempts == 1
    assert profile.thinking_type == "disabled"
    assert profile.reasoning_effort == ""
    assert profile.default_reasoning_effort == ""
    assert profile.reasoning_effort_adapter == "none"
    assert config.llm.get_profile("primary").max_output_tokens == 4096
    assert config.llm.get_profile("primary").retry_policy.max_attempts == 5


def test_model_fingerprint_detects_sampling_change_with_same_model_id(monkeypatch):
    from core.web.services.financial_backtest import service

    config = _decision_config()
    monkeypatch.setattr(decision_mod, "get_config", lambda: config)
    original = service._model_fingerprint("test-qwen")
    config.llm.get_profile("primary").temperature = 0.123
    changed = service._model_fingerprint("test-qwen")

    assert len(original) == len(changed) == 64
    assert changed != original


def test_qwen_decision_payload_explicitly_disables_thinking(monkeypatch):
    config = _decision_config()
    monkeypatch.setattr(decision_mod, "get_config", lambda: config)
    runtime_config = decision_mod.runtime_config_for_decision("test-qwen")
    client = LLMClient(
        config=runtime_config,
        profile_id="financial_ai_backtest",
        backend=lambda _payload: None,
    )

    payload = client._build_payload([{"role": "user", "content": "decide"}], tools=[])

    assert payload["enable_thinking"] is False
    assert "reasoning_effort" not in payload


def test_non_qwen_decision_payload_does_not_receive_qwen_reasoning_parameters(
    monkeypatch,
):
    config = _decision_config(
        model_id="test-gpt",
        model="gpt-test",
        qwen_protocol=False,
        thinking_type="disabled",
        reasoning_effort="",
    )
    monkeypatch.setattr(decision_mod, "get_config", lambda: config)
    runtime_config = decision_mod.runtime_config_for_decision("test-gpt")
    client = LLMClient(
        config=runtime_config,
        profile_id="financial_ai_backtest",
        backend=lambda _payload: None,
    )

    payload = client._build_payload([{"role": "user", "content": "decide"}], tools=[])

    assert "enable_thinking" not in payload
    assert "reasoning_effort" not in payload


def _install_inference_stub(monkeypatch, *, config, content, response_metadata=None):
    captured = {}
    client_marker = object()

    def get_client(*, profile_id, config):
        captured["profile_id"] = profile_id
        captured["runtime_config"] = config
        return client_marker

    def invoke(client, messages, **kwargs):
        captured["client"] = client
        captured["messages"] = messages
        captured.update(kwargs)
        return SimpleNamespace(
            content=content,
            response_metadata=response_metadata
            or {"usage_observation": {"total_tokens": 12}},
        )

    monkeypatch.setattr(decision_mod, "get_config", lambda: config)
    monkeypatch.setattr(decision_mod, "get_llm_client", get_client)
    monkeypatch.setattr(decision_mod, "invoke_llm", invoke)
    return captured, client_marker


def _decision_input():
    return {
        "symbol": "sh600000",
        "asOfDate": "2024-01-03",
        "strategy": "持有至趋势反转",
        "maxPositionPct": 80,
        "portfolio": {"date": "2024-01-03", "cash": 100_000, "shares": 0},
        "dailyBars": [
            {"date": "2024-01-02", "close": 10.0},
            {"date": "2024-01-03", "close": 10.2},
        ],
    }


def test_infer_decision_uses_stateless_tool_free_context(monkeypatch):
    config = _decision_config()
    captured, client_marker = _install_inference_stub(
        monkeypatch,
        config=config,
        content='{"targetWeight":25,"reason":"趋势仍然向上","confidence":0.8}',
    )

    result = decision_mod.infer_decision(
        agent_id="agent-1",
        model_id="test-qwen",
        run_id="run-1",
        decision_input=_decision_input(),
        max_position_pct=80,
    )

    context = captured["context"]
    profile = captured["runtime_config"].llm.get_profile("financial_ai_backtest")
    assert result["targetWeight"] == 25
    assert captured["client"] is client_marker
    assert captured["profile_id"] == "financial_ai_backtest"
    assert captured["tools"] == []
    assert [item["role"] for item in captured["messages"]] == ["system", "user"]
    assert context.surface == "financial_ai_backtest"
    assert context.run_kind == "stateless_historical_decision"
    assert context.conversation_bound is False
    assert context.session_id == ""
    assert context.run_id == "run-1:2024-01-03"
    assert captured["metadata"]["disableAutomaticRetries"] is True
    assert profile.max_output_tokens == 512
    assert profile.retry_policy.max_attempts == 1


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"targetWeight":81,"reason":"超过策略上限"}',
    ],
    ids=["invalid-json", "out-of-range-position"],
)
def test_infer_decision_fails_closed_on_invalid_model_output(monkeypatch, content):
    config = _decision_config()
    captured, _client = _install_inference_stub(
        monkeypatch, config=config, content=content
    )

    with pytest.raises(BacktestInputError):
        decision_mod.infer_decision(
            agent_id="agent-1",
            model_id="test-qwen",
            run_id="run-1",
            decision_input=_decision_input(),
            max_position_pct=80,
        )

    assert captured["tools"] == []
    assert captured["metadata"]["disableAutomaticRetries"] is True


def test_infer_decision_fails_closed_on_length_truncated_response(monkeypatch):
    config = _decision_config()
    captured, _client = _install_inference_stub(
        monkeypatch,
        config=config,
        content='{"targetWeight":25,"reason":"valid-looking prefix"}',
        response_metadata={
            "finish_reason": "length",
            "usage_observation": {"total_tokens": 512},
        },
    )

    with pytest.raises(BacktestInputError):
        decision_mod.infer_decision(
            agent_id="agent-1",
            model_id="test-qwen",
            run_id="run-1",
            decision_input=_decision_input(),
            max_position_pct=80,
        )

    assert captured["tools"] == []


def test_decision_input_excludes_bars_after_as_of_date():
    snapshot = SimpleNamespace(
        symbol="sh600000",
        warmup_candles=(Candle("2023-12-29", 9.8, 10.0, 9.7, 9.9, 100),),
        candles=(
            Candle("2024-01-02", 10.0, 10.2, 9.9, 10.1, 100),
            Candle("2024-01-03", 10.1, 10.3, 10.0, 10.2, 110),
            Candle("2024-01-04", 10.2, 10.4, 10.1, 10.3, 120),
        ),
    )

    decision_input = decision_mod.build_decision_input(
        snapshot,
        {"strategy": "test", "maxPositionPct": 80},
        as_of_date="2024-01-03",
        portfolio={"date": "2024-01-03", "cash": 100_000},
    )

    assert [bar["date"] for bar in decision_input["dailyBars"]] == [
        "2023-12-29",
        "2024-01-02",
        "2024-01-03",
    ]
    assert all(
        bar["date"] <= decision_input["asOfDate"] for bar in decision_input["dailyBars"]
    )
