# -*- coding: utf-8 -*-
"""Replay projection de-duplication must not depend on adjacency."""

from __future__ import annotations

from core.chat.message_identity import dedupe_messages_by_identity, message_identity_key


def _assistant(text: str, *, turn_id: str = "turn-1", item_id: str = "answer", revision: int = 1, kind: str = "") -> dict:
    metadata = {"turnId": turn_id, "itemId": item_id, "revision": revision, "sequence": revision}
    if kind:
        metadata["kind"] = kind
    return {"role": "assistant", "content": text, "metadata": metadata}


def _user(text: str, *, turn_id: str = "turn-1") -> dict:
    return {"role": "user", "content": text, "metadata": {"turnId": turn_id}}


def _tool_result(payload: str = "tool output") -> dict:
    return {"role": "tool", "content": payload, "metadata": {"turnId": "turn-1", "kind": "tool_result"}}


def test_duplicate_rows_are_merged_across_interleaved_events() -> None:
    messages = [
        _user("重构导出脚本"),
        _assistant("完成。"),
        _tool_result(),
        {"role": "system", "content": "context compression", "metadata": {"kind": "context_compression_marker"}},
        _assistant("完成。"),
    ]

    deduped = dedupe_messages_by_identity(messages)

    assert [message["role"] for message in deduped] == ["user", "assistant", "tool", "system"]
    assert [message["content"] for message in deduped] == [
        "重构导出脚本",
        "完成。",
        "tool output",
        "context compression",
    ]


def test_distinct_items_with_identical_text_stay_separate() -> None:
    messages = [
        _assistant("done", item_id="commentary", revision=1),
        _assistant("done", item_id="final_answer", revision=1),
    ]

    deduped = dedupe_messages_by_identity(messages)

    assert len(deduped) == 2
    assert [message["metadata"]["itemId"] for message in deduped] == ["commentary", "final_answer"]


def test_later_revision_replaces_earlier_one_in_place() -> None:
    messages = [
        _user("继续"),
        _assistant("streaming fragment", revision=1),
        _tool_result(),
        _assistant("final answer", revision=2),
        _user("下一轮"),
    ]

    deduped = dedupe_messages_by_identity(messages)

    assert [message["content"] for message in deduped] == ["继续", "final answer", "tool output", "下一轮"]


def test_rows_without_turn_scope_still_dedupe_by_content_identity() -> None:
    first = {"role": "system", "content": "resume notice", "metadata": {"kind": "hot_restart_resume"}}
    second = {"role": "system", "content": "resume notice", "metadata": {"kind": "hot_restart_resume"}}

    assert message_identity_key(first) == message_identity_key(second)
    assert len(dedupe_messages_by_identity([first, second])) == 1
