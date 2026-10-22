# -*- coding: utf-8 -*-
"""Compression preflight scan slicing: bit-identical estimates + GIL yields.

Hard gate (GIL relief batch T3): slicing the long preflight scans with
cooperative yields must not change any estimated token count or eligibility
decision. The frozen-history pins below were recorded against the
pre-change implementation and must stay bit-identical afterwards; the yield
counting tests are the behavioral red baseline (zero yields before, nonzero
after).
"""

from __future__ import annotations

import pytest

from core.orchestration import turn_compression
from core.orchestration.turn_compression import build_token_budget_window
from tools import token_manager
from tools.token_manager import (
    _estimate_message_content_tokens,
    estimate_messages_tokens,
    estimate_messages_tokens_uncached,
    estimate_messages_tokens_with_tool_payloads,
    estimate_tokens_precise,
)


# --- Frozen history (deterministic; literal pins recorded pre-change) --------


def _frozen_history() -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": "你是上下文压缩预算窗回归钉。"},
    ]
    for index in range(24):
        call_id = f"call-{index:02d}"
        messages.append({
            "role": "assistant",
            "content": "" if index % 2 else f"iteration {index} reply 中文混合 ascii tail",
            "tool_calls": [{
                "id": call_id,
                "name": "search",
                "function": {"name": "search", "arguments": f'{{"query":"q{index}"}}'},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": (
                f"result {index} " + "x" * (40 + index * 7)
                + " 结果文本" * (index % 3 + 1)
            ),
        })
        if index % 4 == 3:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"follow-up {index} 跟进"},
                    {"type": "image_url", "image_url": {"url": "https://example/img"}},
                ],
            })
    messages.append({"role": "user", "content": "current request 当前请求"})
    return messages


# Literal anchors: hand-computed from estimate_tokens_precise's documented
# arithmetic (ascii/4 + whitespace/6 + chinese/1.5, ×1.2, +50 per call).
def test_estimate_tokens_precise_hand_pinned_literals() -> None:
    assert estimate_tokens_precise("abcd") == 51  # int(1.0*1.2)+50
    assert estimate_tokens_precise("你") == 50  # int((1/1.5)*1.2)+50
    assert estimate_tokens_precise("ab你") == 51  # int((2/4+1/1.5)*1.2)+50
    assert estimate_tokens_precise("a b\ncd") == 51  # int((4/4+2/6)*1.2)+50


def test_estimated_tokens_bit_identical_for_frozen_history() -> None:
    messages = _frozen_history()
    # Recorded pre-change: cached, uncached and the per-message reference must
    # agree bit-for-bit; the literal total pins any arithmetic drift.
    cached = estimate_messages_tokens(messages)
    uncached = estimate_messages_tokens_uncached(messages)
    reference = sum(
        _estimate_message_content_tokens(token_manager._message_content(message))
        for message in messages
    )
    assert cached == uncached == reference == 4996


def test_threshold_estimator_bit_identical_for_frozen_history() -> None:
    messages = _frozen_history()
    total = estimate_messages_tokens(messages)
    # Recorded pre-change literals. Far under threshold returns the rough
    # upper bound; near/over returns the precise scan — both deterministic.
    # The tool-payload variant meters joined text (one +50 per message), so
    # its total legitimately differs from the per-block content estimator.
    assert token_manager.estimate_messages_tokens_for_threshold(messages, 10) == 4996
    assert token_manager.estimate_messages_tokens_for_threshold(messages, total) == total
    assert estimate_messages_tokens_with_tool_payloads(messages, 10) == 4307
    assert estimate_messages_tokens_with_tool_payloads(messages, total * 10) == 9005


def test_budget_window_frozen_history_bit_identical_to_reference() -> None:
    messages = _frozen_history()
    total = estimate_messages_tokens(messages)
    hard_limit = total // 2  # deterministic given the frozen content

    window, tokens, applied = build_token_budget_window(
        messages, hard_limit=hard_limit, estimator=estimate_messages_tokens,
    )

    # In-test greedy reference of the documented retention semantics (system
    # prefix and latest user always required, newest group first, stop at
    # first overflow; frozen shape pairs each tool result with its preceding
    # call group).
    required = {0, len(messages) - 1}
    groups: list[list[int]] = []
    current: list[int] | None = None
    for index, message in enumerate(messages):
        if index in required:
            current = None
            continue
        if message["role"] == "tool":
            if current is not None:
                current.append(index)
                continue
        current = [index]
        groups.append(current)
    kept: set[int] = set(required)
    running = estimate_messages_tokens([messages[i] for i in sorted(kept)])
    for group in reversed(groups):
        candidate = kept.union(group)
        candidate_tokens = estimate_messages_tokens([messages[i] for i in sorted(candidate)])
        if candidate_tokens > hard_limit:
            break
        kept, running = candidate, candidate_tokens
    kept_list = [messages[i] for i in sorted(kept)]
    assert applied is True
    assert window == kept_list
    assert tokens == running == 2458  # recorded pre-change


def test_budget_window_records_eligible_decision_bit_identically() -> None:
    # The compress-gate eligibility decision is estimated > hard_limit; pin it
    # for the frozen history against a hand-recorded limit.
    messages = _frozen_history()
    total = estimate_messages_tokens(messages)
    assert total > 4995  # eligible for compression at the recorded limit
    assert turn_compression.evaluate_context_budget_preflight(
        estimated_tokens=total, context_input_hard_limit=total - 1,
    ) == {
        "exhausted": True,
        "guardReason": "input_over_hard_limit",
        "estimatedTokens": total,
        "hardLimit": total - 1,
    }


# --- Yield counting (red before the change, green after) --------------------


def _fixed_estimator(per_message: int = 10):
    return lambda messages: per_message * len(messages)


def test_budget_window_yields_between_group_sweeps(monkeypatch: pytest.MonkeyPatch) -> None:
    yields: list[int] = []
    monkeypatch.setattr(turn_compression, "_cooperative_yield", lambda: yields.append(1))
    messages = [{"role": "user", "content": f"m{index}"} for index in range(48)]

    build_token_budget_window(messages, hard_limit=480, estimator=_fixed_estimator())

    # One full estimator sweep per group: a long scan must hand the GIL back
    # dozens of times, not once per second-long stretch.
    assert len(yields) >= 24


def test_budget_window_small_input_yields_little(monkeypatch: pytest.MonkeyPatch) -> None:
    yields: list[int] = []
    monkeypatch.setattr(turn_compression, "_cooperative_yield", lambda: yields.append(1))
    messages = [{"role": "user", "content": f"m{index}"} for index in range(3)]

    build_token_budget_window(messages, hard_limit=30, estimator=_fixed_estimator())

    assert len(yields) <= 4  # per-group scheduling only, no fixed tax


def test_token_scan_yields_inside_estimator(monkeypatch: pytest.MonkeyPatch) -> None:
    yields: list[int] = []
    monkeypatch.setattr(token_manager, "_cooperative_yield", lambda: yields.append(1))
    messages = [
        {"role": "user", "content": f"m{index} " + "字" * (index % 5)}
        for index in range(120)
    ]

    assert estimate_messages_tokens(messages) > 0
    assert len(yields) >= 120 // token_manager._SCAN_YIELD_EVERY_MESSAGES


def test_tool_payload_estimator_yields_on_precise_path(monkeypatch: pytest.MonkeyPatch) -> None:
    yields: list[int] = []
    monkeypatch.setattr(token_manager, "_cooperative_yield", lambda: yields.append(1))
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"c{i}", "function": {"name": "t", "arguments": f'{{"q":"{i}"}}'}}],
        }
        for i in range(100)
    ]

    estimate = estimate_messages_tokens_with_tool_payloads(messages, 10**9)

    assert estimate > 0
    assert len(yields) >= 100 // token_manager._SCAN_YIELD_EVERY_MESSAGES
