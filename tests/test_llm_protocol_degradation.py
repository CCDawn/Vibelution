# -*- coding: utf-8 -*-
"""LLM 协议错误止血批（2026-10-02 事件）回归测试。

覆盖三件事：
- A: 恢复表键名漂移防护（core/llm/recovery.py）——分类器产出的每个类别都有
  显式恢复动作，legacy ``protocol_error`` 键保留兼容，漂移在 import 时报错。
- B: aggregator/relay 通道协议错误有界重试（core/llm/client.py）——窄门
  （通道 + provider_protocol_error + "litellm." 佐证）全部满足才重试，独立
  小预算最多 2 次，直连 provider 行为完全不变，不挤占 5xx 主重试预算。
- C: 「不认参数」去参降级重发——解析被点名参数、剥参后立即重发、成功后有
  warning 与 telemetry 标注，同一请求最多剥 2 轮，预算与 B 共享。
"""

from __future__ import annotations

import pytest

import core.llm.client as client_mod
from core.llm.client import (
    LLMClient,
    _named_unsupported_params_present_in_payload,
    _parse_unsupported_params,
    _strip_unsupported_params,
)
from core.llm.errors import CLASSIFIER_CATEGORIES
from core.llm.recovery import _ACTION_FOR_CATEGORY, plan_recovery
from core.llm.types import LLMError
from tests.helpers.isolated_config import isolated_settings_config


# ---------------------------------------------------------------------------
# 共享夹具
# ---------------------------------------------------------------------------


def make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", False)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    return isolated_settings_config(**kwargs)


def _make_config_with_service_class(service_class: str, **overrides):
    """构建指定 service_class 的 aggregator/relay/direct 测试配置。

    litellm UnsupportedParamsError 复现环境：chat_completions 传输 +
    reasoning_effort_adapter=reasoning_effort，payload 顶层携带
    reasoning_effort（2026-10-02 事件的请求形态）。
    """
    config = make_config(
        **{
            "llm.providers.default.kind": "openai_compatible",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://agg.example.test/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "deepseek-v4.1-flash",
            "llm.profiles.primary.reasoning_effort": "high",
            "llm.profiles.primary.reasoning_effort_values": ["low", "medium", "high"],
            "llm.profiles.primary.reasoning_effort_adapter": "reasoning_effort",
            **overrides,
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    provider.__dict__["service_class"] = service_class
    return config


_CHAT_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "deepseek-v4.1-flash",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _FakeUnifiedLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, tag: str = "") -> None:
        self.warnings.append(str(msg))


@pytest.fixture(autouse=True)
def _quiet_llm_telemetry(monkeypatch):
    """LLM 场景事件与退避睡眠默认静音；事件捕获测试在用例内再覆盖。"""
    monkeypatch.setattr(client_mod, "_sleep_with_llm_cancel_check", lambda _seconds: None)
    monkeypatch.setattr(client_mod, "_record_llm_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(client_mod, "_publish_llm_status_event", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _isolated_route_unsupported_params_cache():
    """per-route 不支持参数负缓存是模块级状态，逐用例隔离保证既有断言
    （剥参探测次数、事件序列）不因用例间缓存泄漏而漂移。"""
    client_mod._reset_llm_route_unsupported_params_cache()
    yield
    client_mod._reset_llm_route_unsupported_params_cache()


def _unsupported_params_error(param: str) -> Exception:
    return Exception(
        f"litellm.UnsupportedParamsError: openai does not support parameters: ['{param}']"
    )


# ---------------------------------------------------------------------------
# A: 恢复表键名漂移防护
# ---------------------------------------------------------------------------


def test_recovery_table_covers_every_classifier_category():
    """分类器能构造的每个类别都必须有显式恢复动作（不允许 .get 静默默认）。"""
    for category in CLASSIFIER_CATEGORIES:
        assert category in _ACTION_FOR_CATEGORY, f"missing explicit action for {category}"
        decision = plan_recovery(LLMError(category, "probe", retryable=False))
        assert decision.action == _ACTION_FOR_CATEGORY[category]


def test_recovery_table_keeps_legacy_protocol_error_key():
    """legacy protocol_error 键保留兼容（分类器不产出，旧显式 LLMError 仍走它）。"""
    assert _ACTION_FOR_CATEGORY["protocol_error"] == "retry_without_streaming"


def test_recovery_table_keeps_provider_protocol_error_fail_fast():
    """provider_protocol_error 保持 fail_fast（真协议错误确定性复现）；其聚合器
    非确定性子集的恢复由 client 层 B/C 窄门负责，不改 fail-closed 设计。"""
    decision = plan_recovery(
        LLMError("provider_protocol_error", "provider 请求参数错误", retryable=False)
    )
    assert decision.action == "fail_fast"
    assert decision.retryable is False
    assert decision.stop_current_turn is True


def test_recovery_table_explicit_payload_protocol_error_entry():
    """payload_protocol_error 曾是键名漂移的活实例（静默默认），现在显式入表。"""
    assert _ACTION_FOR_CATEGORY["payload_protocol_error"] == "fail_fast"
    decision = plan_recovery(LLMError("payload_protocol_error", "本地校验失败", retryable=False))
    assert decision.action == "fail_fast"
    assert decision.stop_current_turn is True


def test_recovery_drift_guard_rejects_uncovered_classifier_category(monkeypatch):
    """分类器新增类别而恢复表未跟时，import 期守卫必须报错而不是静默吞掉。"""
    import core.llm.recovery as recovery_mod

    monkeypatch.setattr(
        recovery_mod, "CLASSIFIER_CATEGORIES", ("brand_new_category",)
    )
    with pytest.raises(ValueError, match="drifted"):
        recovery_mod._validate_table_covers_classifier_categories()


# ---------------------------------------------------------------------------
# C 前置：参数解析与剥参纯函数
# ---------------------------------------------------------------------------


def test_parse_unsupported_params_single_quoted_list():
    assert _parse_unsupported_params(
        "litellm.UnsupportedParamsError: openai does not support parameters: ['reasoning_effort']"
    ) == ("reasoning_effort",)


def test_parse_unsupported_params_multi_param_and_double_quotes():
    text = "openai does not support parameters: ['reasoning_effort', \"top_p\", 'temperature']"
    assert _parse_unsupported_params(text) == ("reasoning_effort", "top_p", "temperature")


def test_parse_unsupported_params_no_match_or_empty_list():
    assert _parse_unsupported_params("some unrelated provider failure") == ()
    assert _parse_unsupported_params("does not support parameters: []") == ()
    assert _parse_unsupported_params("") == ()


def test_parse_unsupported_params_case_insensitive_and_order_preserved():
    text = (
        "Does Not Support Parameters: ['alpha'] ... "
        "does not support parameters: ['alpha', 'beta']"
    )
    assert _parse_unsupported_params(text) == ("alpha", "beta")


def test_strip_unsupported_params_only_removes_named_keys_and_is_pure():
    payload = {"model": "deepseek-v4.1-flash", "reasoning_effort": "high", "temperature": 0.7}
    stripped = _strip_unsupported_params(payload, ("reasoning_effort",))
    assert stripped == {"model": "deepseek-v4.1-flash", "temperature": 0.7}
    # 原 payload 不被原地修改（调用方持有引用，不能有副作用）。
    assert payload.get("reasoning_effort") == "high"
    # 未出现在 payload 里的参数是 no-op。
    assert _strip_unsupported_params(payload, ("absent_param",)) == payload


def test_named_unsupported_params_filters_to_payload_presence():
    exc = Exception("does not support parameters: ['reasoning_effort', 'absent_one']")
    assert _named_unsupported_params_present_in_payload(
        exc, {"model": "m", "reasoning_effort": "high"}
    ) == ("reasoning_effort",)
    assert _named_unsupported_params_present_in_payload(
        Exception("unrelated"), {"reasoning_effort": "high"}
    ) == ()


# ---------------------------------------------------------------------------
# C: 去参降级重发（invoke 非流式路径）
# ---------------------------------------------------------------------------


def test_unsupported_param_stripped_then_request_succeeds_with_telemetry(monkeypatch):
    """剥参重发成功：payload 去掉被点名参数、场景事件与 warning 都要标注。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[bool] = []
    scene: list[tuple[tuple, dict]] = []
    fake_logger = _FakeUnifiedLogger()

    def backend(payload):
        calls.append("reasoning_effort" in payload)
        if len(calls) == 1:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *a, **k: scene.append((a, k))
    )
    monkeypatch.setattr("core.logging.logger", fake_logger)

    message = LLMClient(config=config, backend=backend).invoke(
        [{"role": "user", "content": "ping"}]
    )

    assert message.content == "ok"
    # 首次带 reasoning_effort 被拒；剥参后立即重发成功，且只剥这一个参数。
    assert calls == [True, False]
    degraded = [k for a, k in scene if a[1] == "llm.invoke.unsupported_params_degraded"]
    assert degraded and degraded[0]["fields"]["strippedParams"] == ["reasoning_effort"]
    recovered = [k for a, k in scene if a[1] == "llm.invoke.protocol_degrade_recovered"]
    assert recovered and recovered[0]["fields"]["unsupportedParamsStripped"] is True
    # warning 携带被剥参数名 + 模型 + 通道，且不携带 API key。
    assert any("reasoning_effort" in w for w in fake_logger.warnings)
    assert any("deepseek-v4.1-flash" in w for w in fake_logger.warnings)
    assert all("test-key" not in w for w in fake_logger.warnings)


def test_two_degrade_rounds_exhaust_and_third_unknown_param_fails_normally():
    """连续两轮不同参数都能剥；第三轮预算耗尽，照常失败（总尝试 1+2）。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[tuple[bool, bool, bool]] = []

    def backend(payload):
        calls.append(
            (
                "reasoning_effort" in payload,
                "temperature" in payload,
                "max_tokens" in payload,
            )
        )
        if len(calls) == 1:
            raise _unsupported_params_error("reasoning_effort")
        if len(calls) == 2:
            raise _unsupported_params_error("temperature")
        raise _unsupported_params_error("max_tokens")

    with pytest.raises(LLMError) as exc_info:
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "provider_protocol_error"
    assert len(calls) == 3
    assert calls[0] == (True, True, True)
    assert calls[1] == (False, True, True)
    assert calls[2] == (False, False, True)


def test_param_strip_budget_is_per_request(monkeypatch):
    """剥参预算按请求独立：上一请求剥过参不影响下一请求的完整预算。

    2026-10-06 起 route 级负缓存会让下一请求直接预剥（免探测）；为继续
    单测「预算按请求隔离」这一语义，这里在两通之间显式清空缓存，回到
    无记忆形态。
    """
    config = _make_config_with_service_class("aggregator")
    calls: list[bool] = []

    def backend(payload):
        calls.append("reasoning_effort" in payload)
        if len(calls) % 2 == 1:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    client = LLMClient(config=config, backend=backend)
    assert client.invoke([{"role": "user", "content": "ping"}]).content == "ok"
    client_mod._reset_llm_route_unsupported_params_cache()
    assert client.invoke([{"role": "user", "content": "ping"}]).content == "ok"
    # 两个请求各自经历「带参被拒 → 剥参成功」，第二个请求预算未被上一请求吃掉。
    assert calls == [True, False, True, False]


def test_param_strip_applies_on_direct_provider_too():
    """C 无通道窄门（更根本的一刀）：直连 provider 上被点名的参数同样剥除。"""
    config = _make_config_with_service_class("official_api")
    calls: list[bool] = []

    def backend(payload):
        calls.append("reasoning_effort" in payload)
        if len(calls) == 1:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    message = LLMClient(config=config, backend=backend).invoke(
        [{"role": "user", "content": "ping"}]
    )
    assert message.content == "ok"
    assert calls == [True, False]


# ---------------------------------------------------------------------------
# B: 聚合器/中转通道协议错误有界重试
# ---------------------------------------------------------------------------


def test_aggregator_litellm_protocol_error_retries_twice_then_succeeds():
    """窄门全满足 → 最多重试 2 次，第 3 次尝试成功。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        if len(calls) < 3:
            raise Exception("litellm.BadRequestError: pool node rejected the request shape")
        return dict(_CHAT_OK)

    message = LLMClient(config=config, backend=backend).invoke(
        [{"role": "user", "content": "ping"}]
    )
    assert message.content == "ok"
    assert len(calls) == 3


def test_aggregator_protocol_retry_budget_exhausts_to_normal_failure():
    """重试耗尽 → 照常失败：1 次原发 + 2 次协议重试后 raise。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        raise Exception("litellm.BadRequestError: pool node rejected the request shape")

    with pytest.raises(LLMError) as exc_info:
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "provider_protocol_error"
    assert len(calls) == 3


def test_direct_provider_never_gets_protocol_retry():
    """直连 provider（service_class 不在集合）：行为完全不变，不重试。"""
    config = _make_config_with_service_class("official_api")
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        raise Exception("litellm.BadRequestError: pool node rejected the request shape")

    with pytest.raises(LLMError):
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])
    assert calls == [1]


def test_relay_service_class_also_gets_protocol_retry():
    """relay 通道同属窄门集合。"""
    config = _make_config_with_service_class("relay")
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        if len(calls) < 2:
            raise Exception("litellm.BadRequestError: pool node rejected the request shape")
        return dict(_CHAT_OK)

    message = LLMClient(config=config, backend=backend).invoke(
        [{"role": "user", "content": "ping"}]
    )
    assert message.content == "ok"
    assert len(calls) == 2


def test_protocol_error_without_litellm_evidence_does_not_retry():
    """无 "litellm." 佐证（真确定性参数错误）：不重试，保持 fail-closed。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        raise Exception("bad_request: invalid params unknown-field")

    with pytest.raises(LLMError) as exc_info:
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "provider_protocol_error"
    assert calls == [1]


def test_transient_server_error_main_budget_not_expanded():
    """5xx 走主重试预算：恰好 max_attempts 次调用，协议小预算不为其扩容。"""
    config = _make_config_with_service_class(
        "aggregator", **{"llm.profiles.primary.retry_policy.max_attempts": 2}
    )
    calls: list[int] = []

    def backend(payload):
        calls.append(1)
        raise Exception("litellm.BadGatewayError: OpenAIException - upstream node unavailable")

    with pytest.raises(LLMError) as exc_info:
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "server_error"
    assert len(calls) == 2


def test_degrade_then_transient_failure_keeps_main_budget_separate():
    """先剥参（消耗 1 格协议预算）再遇 5xx：5xx 仍按主预算退避重试，互不挤占。"""
    config = _make_config_with_service_class(
        "aggregator", **{"llm.profiles.primary.retry_policy.max_attempts": 3}
    )
    calls: list[str] = []

    def backend(payload):
        if "reasoning_effort" in payload:
            calls.append("unsupported")
            raise _unsupported_params_error("reasoning_effort")
        calls.append("server_error")
        raise Exception("litellm.BadGatewayError: OpenAIException - upstream node unavailable")

    with pytest.raises(LLMError) as exc_info:
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    assert exc_info.value.category == "server_error"
    # 1 次剥参前 + 主预算 3 次 5xx（剥参后的那次 + 2 次主重试）。
    assert calls == ["unsupported", "server_error", "server_error", "server_error"]


# ---------------------------------------------------------------------------
# B/C: 流式路径（responses 传输，复用既有 wire 测试形态）
# ---------------------------------------------------------------------------


def _make_stream_config(service_class: str, **overrides):
    config = make_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://pixel.try-chatapi.com/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": "responses",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.retry_policy.max_attempts": 3,
            "llm.profiles.primary.reasoning_effort": "high",
            "llm.profiles.primary.reasoning_effort_values": ["low", "medium", "high"],
            "llm.profiles.primary.reasoning_effort_adapter": "reasoning_object",
            **overrides,
        }
    )
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)
    provider.__dict__["service_class"] = service_class
    return config


def _completed_response_events():
    return iter(
        [
            {"type": "response.output_text.delta", "delta": "recovered"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-recovered",
                    "status": "completed",
                    "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
                },
            },
        ]
    )


def test_stream_unsupported_param_stripped_and_succeeded_event_flagged(monkeypatch):
    """流式：reasoning 被点名 → 剥参重发成功，succeeded 事件带退化标注。"""
    config = _make_stream_config("aggregator")
    calls: list[object] = []
    scene: list[tuple[tuple, dict]] = []

    def default_responses_backend(payload):
        calls.append(payload.get("reasoning"))
        if len(calls) == 1:
            raise _unsupported_params_error("reasoning")
        return _completed_response_events()

    monkeypatch.setattr(client_mod, "_default_responses_backend", default_responses_backend)
    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *a, **k: scene.append((a, k))
    )

    events = list(LLMClient(config=config).stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert calls[0] is not None and calls[1] is None
    assert any(a[1] == "llm.stream.unsupported_params_degraded" for a, k in scene)
    succeeded = [k for a, k in scene if a[1] == "llm.stream.succeeded"]
    assert succeeded
    fields = succeeded[0]["fields"]
    assert fields["unsupportedParamsStripped"] is True
    assert fields["strippedParams"] == ["reasoning"]
    assert fields["aggregatorProtocolRetries"] == 0


def test_stream_aggregator_litellm_protocol_error_retries_without_strip(monkeypatch):
    """流式 B 窄门：litellm 佐证但无被点名参数 → 同 payload 重放一次成功。"""
    config = _make_stream_config("aggregator")
    calls: list[int] = []
    scene: list[tuple[tuple, dict]] = []

    def default_responses_backend(payload):
        calls.append(1)
        if len(calls) < 2:
            raise Exception("litellm.BadRequestError: pool node rejected the request shape")
        return _completed_response_events()

    monkeypatch.setattr(client_mod, "_default_responses_backend", default_responses_backend)
    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *a, **k: scene.append((a, k))
    )

    events = list(LLMClient(config=config).stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    assert len(calls) == 2
    assert any(a[1] == "llm.stream.protocol_retrying" for a, k in scene)
    succeeded = [k for a, k in scene if a[1] == "llm.stream.succeeded"]
    assert succeeded
    assert succeeded[0]["fields"]["aggregatorProtocolRetries"] == 1


def test_stream_direct_provider_protocol_error_fails_fast(monkeypatch):
    """流式直连 provider：无窄门，provider_protocol_error 照常立即失败。"""
    config = _make_stream_config("official_api")
    calls: list[int] = []

    def default_responses_backend(payload):
        calls.append(1)
        raise Exception("litellm.BadRequestError: pool node rejected the request shape")

    monkeypatch.setattr(client_mod, "_default_responses_backend", default_responses_backend)

    with pytest.raises(LLMError) as exc_info:
        list(LLMClient(config=config).stream_events([{"role": "user", "content": "ping"}]))

    assert exc_info.value.category == "provider_protocol_error"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# D: per-route 不支持参数负缓存（2026-10-06 固定开销治理）
#
# 聚合池节点拒 reasoning_effort 的 400 探测 + 剥参重发是每通重付的固定开销；
# 剥参重发成功后 route 的能力事实稳定，按 route_key 负缓存、下次发送前预剥。
# ---------------------------------------------------------------------------


def test_second_invoke_same_route_pre_strips_without_probe(monkeypatch):
    """同 route 第二通直接预剥：不再出现 400 探测，事件流标 cache hit。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[bool] = []
    scene: list[tuple[tuple, dict]] = []

    def backend(payload):
        calls.append("reasoning_effort" in payload)
        if "reasoning_effort" in payload:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *a, **k: scene.append((a, k))
    )

    LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])
    scene.clear()
    LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])

    # 第一通：探测（带参）→ 剥参重发成功；第二通：首发即无参，只有一次后端调用。
    assert calls == [True, False, False]
    assert not any(a[1] == "llm.invoke.unsupported_params_degraded" for a, k in scene)
    hits = [k for a, k in scene if a[1] == "llm.invoke.unsupported_params_cache_hit"]
    assert hits and hits[0]["fields"]["cacheHit"] is True
    assert hits[0]["fields"]["strippedParams"] == ["reasoning_effort"]


def test_second_stream_same_route_pre_strips_without_probe(monkeypatch):
    """流式路径同 route 第二通直接预剥：不探测，cache hit 事件带参名。"""
    config = _make_stream_config("aggregator")
    calls: list[object] = []
    scene: list[tuple[tuple, dict]] = []

    def default_responses_backend(payload):
        calls.append(payload.get("reasoning"))
        if payload.get("reasoning") is not None:
            raise _unsupported_params_error("reasoning")
        return _completed_response_events()

    monkeypatch.setattr(client_mod, "_default_responses_backend", default_responses_backend)
    monkeypatch.setattr(
        client_mod, "_record_llm_scene_event", lambda *a, **k: scene.append((a, k))
    )

    list(LLMClient(config=config).stream_events([{"role": "user", "content": "ping"}]))
    scene.clear()
    events = list(LLMClient(config=config).stream_events([{"role": "user", "content": "ping"}]))

    assert [event.type for event in events] == ["text_delta", "done"]
    # 第一通：带 reasoning 探测 → 剥参重发成功；第二通：首发即无 reasoning。
    assert calls[0] is not None and calls[1] is None and calls[2] is None
    assert len(calls) == 3
    assert not any(a[1] == "llm.stream.unsupported_params_degraded" for a, k in scene)
    hits = [k for a, k in scene if a[1] == "llm.stream.unsupported_params_cache_hit"]
    assert hits and hits[0]["fields"]["strippedParams"] == ["reasoning"]
    succeeded = [k for a, k in scene if a[1] == "llm.stream.succeeded"]
    assert succeeded
    # 预剥不属于降级：成功事件语义保持原样。
    assert succeeded[0]["fields"]["unsupportedParamsStripped"] is False


def test_cache_isolated_across_provider_and_model(monkeypatch):
    """不同 provider/model 组成不同 route：不吃别家缓存，仍需一次探测。"""
    config_a = _make_config_with_service_class("aggregator")
    config_b = _make_config_with_service_class(
        "aggregator",
        **{
            "llm.providers.default.base_url": "https://other.example.test/v1",
            "llm.profiles.primary.model": "other-model",
        },
    )
    calls_a: list[bool] = []
    calls_b: list[bool] = []

    def backend_a(payload):
        calls_a.append("reasoning_effort" in payload)
        if len(calls_a) == 1:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    def backend_b(payload):
        calls_b.append("reasoning_effort" in payload)
        if "reasoning_effort" in payload:
            raise _unsupported_params_error("reasoning_effort")
        return dict(_CHAT_OK)

    monkeypatch.setattr(client_mod, "_record_llm_scene_event", lambda *a, **k: None)

    LLMClient(config=config_a, backend=backend_a).invoke([{"role": "user", "content": "ping"}])
    LLMClient(config=config_b, backend=backend_b).invoke([{"role": "user", "content": "ping"}])
    LLMClient(config=config_b, backend=backend_b).invoke([{"role": "user", "content": "ping"}])
    # B 与 A 不同 route：首通仍完整探测，第二通才吃到 B 自己的缓存。
    assert calls_a == [True, False]
    assert calls_b == [True, False, False]


def test_cache_written_only_after_degraded_resend_succeeds(monkeypatch):
    """缓存写入条件 = 剥参重发成功：重发仍失败时不写，下一通照常探测。"""
    config = _make_config_with_service_class("aggregator")
    calls: list[bool] = []
    strip_resend_fails = True

    def backend(payload):
        calls.append("reasoning_effort" in payload)
        if "reasoning_effort" in payload:
            raise _unsupported_params_error("reasoning_effort")
        if strip_resend_fails:
            raise Exception("upstream 500 exploded")
        return dict(_CHAT_OK)

    monkeypatch.setattr(client_mod, "_record_llm_scene_event", lambda *a, **k: None)

    with pytest.raises(LLMError):
        LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])
    assert calls.count(True) == 1  # 只有首发带参探测；剥参后的重试都未成功。

    strip_resend_fails = False
    LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])
    # 上一通失败未写缓存：这一通仍要重新探测一次，成功后才写入。
    assert calls.count(True) == 2
    assert calls[-1] is False

    LLMClient(config=config, backend=backend).invoke([{"role": "user", "content": "ping"}])
    # 这一通起缓存生效：首发即预剥。
    assert calls[-1] is False
    assert calls.count(True) == 2
