"""Recovery policy mapping tests for core/llm/recovery.py."""

from __future__ import annotations

from core.llm.errors import LLMError, classify_exception
from core.llm.recovery import plan_recovery



def test_recovery_policy_retries_protocol_error_without_streaming():
    error = LLMError(
        "protocol_error",
        "wire stream adapter did not produce canonical TurnOutcome",
        retryable=False,
    )

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "protocol_error"
    assert decision.action == "retry_without_streaming"
    # Deterministic on the same adapter path, so no same-path transport retry:
    # wait_seconds stays 0 like empty_content_error.
    assert decision.wait_seconds == 0
    assert decision.stop_current_turn is False
    # Marked retryable so the route failure is reported as recoverable.
    assert decision.retryable is True



def test_recovery_policy_keeps_provider_protocol_error_fail_fast():
    error = LLMError("provider_protocol_error", "provider 请求参数错误", retryable=False)

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "provider_protocol_error"
    assert decision.action == "fail_fast"
    assert decision.retryable is False
    assert decision.stop_current_turn is True


def test_recovery_policy_retries_deepseek_thinking_roundtrip_rejection():
    # 生产路径里裸异常先经 client 的 classify_error 包成 LLMError 再上抛，
    # 这里用两种入口验证同一决策：同体重试、不终止当前 turn。
    message = (
        "Error code: 400 - {'error': {'message': 'The `reasoning_content` in "
        "the thinking mode must be passed back to the API'}}"
    )

    for exc in (Exception(message), classify_exception(Exception(message))):
        decision = plan_recovery(exc, attempt=1, max_attempts=5)
        assert decision.category == "server_error"
        assert decision.action == "retry_with_backoff"
        assert decision.retryable is True
        assert decision.stop_current_turn is False
        assert decision.wait_seconds > 0


def test_recovery_policy_stops_turn_after_thinking_roundtrip_retry_budget():
    message = (
        "Error code: 400 - {'error': {'message': 'The `reasoning_content` in "
        "the thinking mode must be passed back to the API'}}"
    )

    decision = plan_recovery(Exception(message), attempt=5, max_attempts=5)

    assert decision.retryable is True
    assert decision.stop_current_turn is True


def test_recovery_policy_retries_answer_channel_leak_with_tools_off():
    error = LLMError(
        "answer_channel_leak",
        "model leaked internal formatting into the final answer channel",
        retryable=True,
    )

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "answer_channel_leak"
    assert decision.action == "retry_answer_without_tools"
    # Same-shape replay would reproduce the leak; the degraded retry must
    # drop both streaming and tools.
    assert decision.disable_streaming is True
    assert decision.disable_tools is True
    assert decision.retryable is True
    assert decision.stop_current_turn is False
    assert decision.action in {
        name
        for name in ("retry_answer_without_tools",)
    }


def test_degraded_retry_actions_include_answer_channel_leak_action():
    from core.llm.recovery import DEGRADED_RETRY_ACTIONS, degraded_retry_overrides

    assert "retry_answer_without_tools" in DEGRADED_RETRY_ACTIONS
    assert degraded_retry_overrides("retry_answer_without_tools") == (True, True)
