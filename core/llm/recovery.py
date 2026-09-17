# -*- coding: utf-8 -*-
"""Recovery policy for normalized LLM failures."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .errors import classify_exception
from .resilience_policy import DEGRADED_RETRY_CATEGORIES
from .types import LLMError


@dataclass(frozen=True)
class LLMRecoveryDecision:
    category: str
    retryable: bool
    action: str
    user_message: str
    wait_seconds: int = 0
    stop_current_turn: bool = False
    disable_streaming: bool = False
    disable_tools: bool = False
    request_context_compression: bool = False


# Attempt-level capability-degradation actions. ``turn_llm_adapter`` executes
# each of these at most once per turn, on the route that just failed, before
# any declared fallback switch (the ladder order is owned by
# ``core/llm/resilience_policy.py``). Keeping the vocabulary next to
# ``_action_for_category`` makes this module the single source of truth for
# what a category's *action* means; the adapter must not re-declare the
# mapping, and the stage side of the same categories is machine-checked below
# against the policy module.
DEGRADED_RETRY_ACTIONS = frozenset(
    {
        "retry_without_streaming",
        "disable_tools_and_retry_without_streaming",
        "retry_answer_without_tools",
    }
)


def degraded_retry_overrides(action: str) -> tuple[bool, bool]:
    """Capability overrides a degraded retry attempt runs with.

    Returns ``(disable_streaming, disable_tools)`` for an action. Both
    degradation actions drop streaming: empty replies and tool-protocol
    breakage are observed on the streamed path, and transport retries only
    apply before the first streamed token anyway. Only the tool-protocol
    action also drops tools, degrading that attempt to a plain text
    completion the turn can still close on.
    """
    if action in {
        "disable_tools_and_retry_without_streaming",
        "retry_answer_without_tools",
    }:
        return True, True
    if action == "retry_without_streaming":
        return True, False
    return False, False


def plan_recovery(
    exc: Exception,
    *,
    attempt: int = 1,
    max_attempts: int = 5,
) -> LLMRecoveryDecision:
    error = classify_exception(exc)
    action = _action_for_category(error.category)
    wait_seconds = _retry_wait_seconds(error, attempt, max_attempts)
    disable_streaming, disable_tools = degraded_retry_overrides(action)
    return LLMRecoveryDecision(
        category=error.category,
        # protocol_error is deterministic on the same adapter path, so same-path
        # transport retries stay off; the decision stays retryable so the route
        # failure is reported as recoverable instead of an immediate hard stop.
        # Its designed escape hatch is the adapter-level degraded
        # ``retry_without_streaming`` below: a request-shape change (streaming
        # off) capped at once per turn by the adapter, not a blind replay.
        retryable=error.retryable or error.category == "protocol_error",
        action=action,
        user_message=str(error),
        wait_seconds=wait_seconds,
        stop_current_turn=_should_stop_current_turn(error, attempt, max_attempts),
        disable_streaming=disable_streaming,
        disable_tools=disable_tools,
        request_context_compression=error.category == "context_length_error",
    )


def _action_for_category(category: str) -> str:
    return _ACTION_FOR_CATEGORY.get(category, "fail_fast")


# Category → action vocabulary (single source of truth for what a category's
# action means). Module-level so tests can machine-check its degraded subset
# against core/llm/resilience_policy.py's stage map.
_ACTION_FOR_CATEGORY: Mapping[str, str] = MappingProxyType(
    {
        "network_error": "retry_with_backoff",
        "timeout": "retry_with_backoff",
        "server_error": "retry_with_backoff",
        "rate_limit": "retry_after_backoff",
        "context_length_error": "compress_context",
        "tool_protocol_error": "disable_tools_and_retry_without_streaming",
        "empty_content_error": "retry_without_streaming",
        "protocol_error": "retry_without_streaming",
        # Answer-channel leak: the model emitted internal formatting (analysis
        # / summary envelopes, legacy tool-call XML, DSML fragments) as the
        # final answer. Same-shape replay would reproduce it, so the one-shot
        # degraded retry changes the request shape: streaming off (the leak was
        # observed on the streamed path) and tools off (legacy-XML tool
        # syntax is the observed inducer). See core/llm/answer_channel_guard.py.
        "answer_channel_leak": "retry_answer_without_tools",
        "capability_error": "fail_fast",
        "quota_error": "fail_fast",
        "auth_error": "fail_fast",
        "configuration_error": "fail_fast",
        "provider_protocol_error": "fail_fast",
        "user_interrupt": "stop",
    }
)


def _validate_degraded_actions_match_policy_stages() -> None:
    """Machine-checked tie between the action vocabulary and the policy stage map.

    Every category whose action is a degraded retry must sit at the policy
    ladder's DEGRADED_RETRY stage, and vice versa. Drift in either module fails
    at import time instead of silently forking the resilience vocabulary.
    """
    degraded_action_categories = {
        category
        for category, action in _ACTION_FOR_CATEGORY.items()
        if action in DEGRADED_RETRY_ACTIONS
    }
    if degraded_action_categories != set(DEGRADED_RETRY_CATEGORIES):
        raise ValueError(
            "core/llm/recovery.py degraded action categories drifted from "
            "core/llm/resilience_policy.py DEGRADED_RETRY_CATEGORIES: "
            f"{sorted(degraded_action_categories)} != {sorted(DEGRADED_RETRY_CATEGORIES)}"
        )


_validate_degraded_actions_match_policy_stages()


def _retry_wait_seconds(error: LLMError, attempt: int, max_attempts: int) -> int:
    if not error.retryable or attempt >= max_attempts:
        return 0
    if error.category == "rate_limit":
        return min(10 * max(attempt, 1), 60)
    if error.category in {"network_error", "timeout", "server_error"}:
        return min(2 ** max(attempt, 1), 8)
    return min(2 ** max(attempt, 1), 30)


def _should_stop_current_turn(error: LLMError, attempt: int, max_attempts: int) -> bool:
    if error.category in {"user_interrupt", "auth_error", "quota_error", "configuration_error"}:
        return True
    if error.category == "capability_error":
        return True
    if error.category in {"context_length_error", "tool_protocol_error", "empty_content_error", "protocol_error", "answer_channel_leak"}:
        return False
    if not error.retryable:
        return True
    return attempt >= max_attempts


__all__ = [
    "DEGRADED_RETRY_ACTIONS",
    "LLMRecoveryDecision",
    "degraded_retry_overrides",
    "plan_recovery",
]
