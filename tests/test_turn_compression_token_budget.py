# -*- coding: utf-8 -*-
"""Token-budget compaction window: codex-parity fallback behaviour."""

from __future__ import annotations

from core.orchestration.turn_compression import build_token_budget_window


def _fixed_estimator(per_message: int = 10):
    return lambda messages: per_message * len(messages)


def test_keeps_everything_when_it_fits() -> None:
    messages = [{"role": "user", "content": f"m{index}"} for index in range(3)]

    window, tokens, applied = build_token_budget_window(
        messages, hard_limit=30, estimator=_fixed_estimator()
    )

    assert applied is True
    assert window == messages
    assert tokens == 30


def test_keeps_newest_messages_that_fit() -> None:
    messages = [{"role": "user", "content": f"m{index}"} for index in range(6)]

    window, tokens, applied = build_token_budget_window(
        messages, hard_limit=30, estimator=_fixed_estimator()
    )

    assert applied is True
    assert [item["content"] for item in window] == ["m3", "m4", "m5"]
    assert tokens == 30


def test_drops_leading_orphan_tool_results() -> None:
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "result"},
        {"role": "user", "content": "next question"},
    ]

    window, _tokens, applied = build_token_budget_window(
        messages, hard_limit=20, estimator=_fixed_estimator()
    )

    assert applied is True
    # The assistant tool call fell out of the window, so its tool result must
    # not survive alone: an orphan tool result breaks the provider chain.
    assert [item["role"] for item in window] == ["user"]


def test_reports_not_applied_when_nothing_fits() -> None:
    messages = [{"role": "user", "content": "too big"}]

    window, tokens, applied = build_token_budget_window(
        messages, hard_limit=5, estimator=_fixed_estimator()
    )

    assert applied is False
    assert window == []
    assert tokens == 0


def test_budget_window_protects_rules_summary_and_current_request() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "system", "content": "history summary"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "current request"},
    ]
    window, tokens, applied = build_token_budget_window(
        messages, hard_limit=30, estimator=_fixed_estimator(),
    )
    assert applied is True
    assert window == [messages[0], messages[1], messages[3]]
    assert tokens == 30


def test_budget_window_cannot_drop_required_context_to_meet_budget() -> None:
    messages = [
        {"role": "system", "content": "required rules"},
        {"role": "user", "content": "current request"},
    ]
    assert build_token_budget_window(
        messages, hard_limit=10, estimator=_fixed_estimator(),
    ) == ([], 0, False)


def test_budget_window_keeps_multicall_and_results_as_one_group() -> None:
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "one"}, {"id": "two"}]},
        {"role": "tool", "tool_call_id": "one", "content": "result one"},
        {"role": "tool", "tool_call_id": "two", "content": "result two"},
        {"role": "user", "content": "current request"},
    ]
    window, _, applied = build_token_budget_window(
        messages, hard_limit=40, estimator=_fixed_estimator(),
    )
    assert applied is True
    assert window == [messages[0], messages[-1]]
    complete, _, _ = build_token_budget_window(
        messages, hard_limit=50, estimator=_fixed_estimator(),
    )
    assert complete == messages
