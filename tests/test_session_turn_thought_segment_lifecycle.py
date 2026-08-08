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
