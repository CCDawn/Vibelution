"""Recovery policy mapping tests for core/llm/recovery.py."""

from __future__ import annotations

from core.llm.errors import LLMError
from core.llm.recovery import plan_recovery
from core.llm.routing import attach_recovery_fallback
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.providers.default.kind", "minimax")
    kwargs.setdefault("llm.providers.default.api_key", "test-key")
    kwargs.setdefault("llm.providers.default.base_url", "https://api.minimaxi.com/v1")
    kwargs.setdefault("llm.profiles.primary.provider_id", "default")
    kwargs.setdefault("llm.profiles.primary.model", "MiniMax-M2.7")
    return isolated_settings_config(**kwargs)


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
    # Marked retryable so the turn survives one fallback route switch.
    assert decision.retryable is True


def test_recovery_policy_attaches_non_streaming_fallback_for_protocol_error():
    config = make_config(
        **{
            "llm.providers.backup.kind": "local",
            "llm.providers.backup.requires_api_key": False,
            "llm.providers.backup.base_url": "http://localhost:8000/v1",
            "llm.profiles.fallback_backup.provider_id": "backup",
            "llm.profiles.fallback_backup.model": "qwen-32b-awq",
            "llm.profiles.fallback_backup.streaming": False,
        }
    )
    decision = plan_recovery(
        LLMError("protocol_error", "Anthropic Messages SSE contains invalid JSON", retryable=False),
        attempt=1,
        max_attempts=5,
    )

    enriched = attach_recovery_fallback(
        decision,
        config=config,
        current_profile_id="primary",
    )

    assert enriched.action == "retry_without_streaming"
    assert enriched.fallback_profile_id == "fallback_backup"


def test_recovery_policy_keeps_provider_protocol_error_fail_fast():
    error = LLMError("provider_protocol_error", "provider 请求参数错误", retryable=False)

    decision = plan_recovery(error, attempt=1, max_attempts=5)

    assert decision.category == "provider_protocol_error"
    assert decision.action == "fail_fast"
    assert decision.retryable is False
    assert decision.stop_current_turn is True
