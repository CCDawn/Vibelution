# -*- coding: utf-8 -*-
"""Per-message incremental context metering contracts.

The agent loop upserts a fresh turn status-bar tail on every iteration, so the
whole-list content signature always misses. Without a per-message memo that
turns every estimate into a full per-character walk of the entire history.

These tests pin two things: results stay bit-identical to the uncached
reference, and only genuinely new/changed messages are re-scanned.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from tools import token_manager as tm
from tools.token_manager import (
    estimate_messages_tokens,
    estimate_messages_tokens_for_threshold,
    estimate_messages_tokens_uncached,
    rough_upper_bound_messages_tokens,
)


class _Message:
    def __init__(self, content):
        self.content = content


@pytest.fixture(autouse=True)
def _clean_caches():
    tm._estimate_cache.clear()
    tm.reset_message_token_memo()
    yield
    tm._estimate_cache.clear()
    tm.reset_message_token_memo()


def _mixed_history(length: int = 24) -> list:
    messages = [
        _Message("system prompt 中文与 ascii 混合 " * 40),
        _Message(None),
        _Message(""),
        {"role": "user", "content": "请检查这段历史 " * 30},
        _Message([{"type": "text", "text": "structured block " * 40}, "plain text"]),
        {"role": "assistant", "content": "", "tool_calls": [{"name": "read_file", "args": {"path": "a.py"}}]},
        {"role": "tool", "content": "tool result " * 30, "tool_call_id": "call-1"},
    ]
    for index in range(length):
        messages.append(_Message(f"iteration {index} 工具结果 " * 60))
    return messages


def test_incremental_scan_is_bit_identical_to_uncached_reference():
    messages = _mixed_history()

    precise_reference = estimate_messages_tokens_uncached(messages)
    rough_reference = rough_upper_bound_messages_tokens(messages)

    scanned = tm._scan_messages_tokens(messages)
    cached = estimate_messages_tokens(messages)
    near_threshold = estimate_messages_tokens_for_threshold(messages, threshold=1)

    assert scanned == (precise_reference, rough_reference)
    assert cached == precise_reference
    assert near_threshold == precise_reference
    # Repeating through the memo must not drift the arithmetic.
    assert tm._scan_messages_tokens(messages) == scanned
    assert estimate_messages_tokens(list(messages)) == precise_reference


def test_appended_status_bar_tail_only_rescans_the_tail(monkeypatch):
    """A rebuilt tail invalidates the whole-list signature, but history costs stay cached."""

    messages = _mixed_history(40)
    history_reference = estimate_messages_tokens_uncached(messages)
    scans = {"n": 0}
    original = tm._estimate_message_content_tokens

    def counting(content):
        scans["n"] += 1
        return original(content)

    monkeypatch.setattr(tm, "_estimate_message_content_tokens", counting)

    first = estimate_messages_tokens_for_threshold(messages, threshold=1)
    first_scan_count = scans["n"]
    assert first_scan_count == len(messages)
    assert first == history_reference

    # Every iteration rebuilds the list and appends a brand-new status bar.
    for iteration in range(1, 6):
        tail_content = f"status bar iteration={iteration} " * 8
        scanned = list(messages) + [_Message(tail_content)]
        value = estimate_messages_tokens_for_threshold(scanned, threshold=1)
        assert value == history_reference + original(tail_content)

    # 5 iterations × 1 new tail = 5 extra per-character walks, not 5 × full history.
    assert scans["n"] - first_scan_count == 5


def test_replaced_content_object_invalidates_the_message_memo():
    message = _Message("original content " * 20)
    messages = [message]
    before = estimate_messages_tokens(messages)

    message.content = "replaced content 中文 " * 60
    tm._estimate_cache.clear()
    after = estimate_messages_tokens(messages)

    assert after != before
    assert after == estimate_messages_tokens_uncached(messages)


def test_memo_is_bounded_by_entries_and_chars():
    for index in range(tm._MESSAGE_TOKEN_MEMO_MAX_ENTRIES + 80):
        tm._estimate_cache.clear()
        estimate_messages_tokens([_Message(f"payload {index} " * 20)])

    assert len(tm._message_token_memo) <= tm._MESSAGE_TOKEN_MEMO_MAX_ENTRIES
    assert tm._message_token_memo_chars <= tm._MESSAGE_TOKEN_MEMO_MAX_CHARS


def test_concurrent_scans_match_the_reference():
    messages = _mixed_history(60)
    reference = estimate_messages_tokens_uncached(messages)

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(
            pool.map(
                lambda _: estimate_messages_tokens_for_threshold(messages, threshold=1),
                range(16),
            )
        )

    assert values == [reference] * len(values)


def test_reset_seam_clears_memo_and_char_counter():
    estimate_messages_tokens([_Message("payload " * 40)])
    assert len(tm._message_token_memo) == 1
    assert tm._message_token_memo_chars > 0

    tm.reset_message_token_memo()

    assert len(tm._message_token_memo) == 0
    assert tm._message_token_memo_chars == 0
