"""Thinking-segment lifecycle: the reasoning row settles to completed when the
stream leaves the thinking stage, without waiting for the turn-level done.

Regression guard: after a thought segment finishes streaming (answer/tool delta
arrives, or the stream stage moves past thinking), the UI must stop the segment
spinner immediately; previously it stayed in_progress until turn commit.
"""

from __future__ import annotations

from core.web.services.session import projection


def _reasoning_item(text: str, status: str = "in_progress", provisional: bool = True) -> dict:
    return {
        "version": 2,
        "id": "turn-reasoning:0",
        "itemId": "turn-reasoning",
        "type": "reasoning",
        "kind": "reasoning",
        "channel": "analysis",
        "phase": "reasoning",
        "status": status,
        "provisional": provisional,
        "terminal": False,
        "sequence": 0,
        "sessionId": "s1",
        "turnId": "turn-1",
        "messageId": "m1",
        "source": "assistant_delta",
        "protocol": "session_detail",
        "text": text,
    }


def _commentary_item(text: str, status: str = "completed", provisional: bool = False) -> dict:
    return {
        "version": 2,
        "id": "turn-commentary:0",
        "itemId": "turn-commentary",
        "type": "commentary",
        "kind": "commentary",
        "channel": "commentary",
        "phase": "commentary",
        "status": status,
        "provisional": provisional,
        "terminal": False,
        "sequence": 1,
        "sessionId": "s1",
        "turnId": "turn-1",
        "messageId": "m1",
        "source": "canonical",
        "protocol": "session_detail",
        "text": text,
    }


def test_thinking_stage_keeps_reasoning_row_in_progress() -> None:
    items = [_reasoning_item("先分析")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析，再看日志",
        done=False,
        stage="model_thinking",
    )
    row = next(item for item in merged if item["kind"] == "reasoning")
    assert row["status"] == "in_progress"
    assert row["provisional"] is True
    assert row["text"] == "先分析，再看日志"


def test_answer_stage_settles_reasoning_row_without_turn_done() -> None:
    items = [_reasoning_item("先分析")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析",
        done=False,
        stage="assistant_response",
    )
    row = next(item for item in merged if item["kind"] == "reasoning")
    assert row["status"] == "completed"
    assert row["provisional"] is False


def test_answer_stage_settles_reasoning_row_while_thought_still_grows() -> None:
    items = [_reasoning_item("先分析")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析，再看日志，最后验证",
        done=False,
        stage="assistant_response",
    )
    row = next(item for item in merged if item["kind"] == "reasoning")
    assert row["status"] == "completed"
    assert row["text"] == "先分析"


def test_answer_stage_without_reasoning_row_creates_completed_row() -> None:
    merged = projection._merge_live_thought_into_turn_items(
        [],
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="已有思考",
        done=False,
        stage="assistant_response",
    )
    assert len(merged) == 1
    assert merged[0]["kind"] == "reasoning"
    assert merged[0]["status"] == "completed"


def test_empty_stage_keeps_legacy_done_bound_behavior() -> None:
    items = [_reasoning_item("先分析")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析，再看日志",
        done=False,
        stage="",
    )
    row = next(item for item in merged if item["kind"] == "reasoning")
    assert row["status"] == "in_progress"


def test_done_still_settles_reasoning_row() -> None:
    items = [_reasoning_item("先分析")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析",
        done=True,
        stage="model_thinking",
    )
    row = next(item for item in merged if item["kind"] == "reasoning")
    assert row["status"] == "completed"


def test_commentary_row_absorbs_overlapping_thought_without_new_reasoning() -> None:
    # Protocol committed the tool-lead summary as commentary; live thought covers
    # it as a substring (mid-stream segment). Must merge into commentary, not add
    # a second reasoning row that would double-paint the thinking.
    items = [_commentary_item("先检查日志")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先检查日志，再看证据链，最后验证结论",
        done=False,
        stage="assistant_response",
    )
    assert len(merged) == 1
    row = merged[0]
    assert row["kind"] == "commentary"
    assert row["text"] == "先检查日志，再看证据链，最后验证结论"
    assert row["status"] == "completed"


def test_commentary_prefix_thought_merges_and_keeps_committed_state() -> None:
    # Committed commentary (completed) stays terminal; only text is upgraded.
    items = [_commentary_item("先检查日志", status="completed")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先检查日志，再看证据链",
        done=True,
        stage="model_thinking",
    )
    assert len(merged) == 1
    assert merged[0]["kind"] == "commentary"
    assert merged[0]["text"] == "先检查日志，再看证据链"
    assert merged[0]["status"] == "completed"


def test_commentary_without_overlap_still_gets_reasoning_row() -> None:
    # Distinct commentary (tool description) and thought do not merge; both stay.
    items = [_commentary_item("执行工具校验")]
    merged = projection._merge_live_thought_into_turn_items(
        items,
        session_id="s1",
        turn_id="turn-1",
        message_id="m1",
        thought="先分析根因",
        done=False,
        stage="model_thinking",
    )
    kinds = [item["kind"] for item in merged]
    assert kinds == ["reasoning", "commentary"]
