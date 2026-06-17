from __future__ import annotations

import json
from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_context_compression_checkpoint,
    append_conversation_event,
    conversation_ledger_path,
    conversation_model_messages_from_events,
    event_has_model_projection,
    event_projection_category,
    latest_ledger_sequence,
    load_conversation_events,
    project_conversation_ledger,
)


def test_conversation_ledger_appends_and_projects_model_messages(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续修复单一事实源"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-1", "name": "cli_tool", "status": "done", "result": "测试通过"}},
        tool_call_id="tool-1",
    )

    events = load_conversation_events(tmp_path, "session-a")
    projection = project_conversation_ledger(events)
    messages = conversation_model_messages_from_events(events)

    assert conversation_ledger_path(tmp_path, "session-a").exists()
    assert [event.sequence for event in events] == [1, 2, 3]
    assert projection.latest_seq == 3
    assert projection.to_metadata()["ledgerSeq"] == 3
    assert latest_ledger_sequence(tmp_path, "session-a") == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "继续修复单一事实源"
    assert messages[1]["role"] == "assistant"
    assert not any(message.get("role") == "tool" for message in messages)
    assert "历史工具结果: cli_tool" in messages[1]["content"]
    assert "测试通过" in messages[1]["content"]


def test_conversation_ledger_append_does_not_full_scan_existing_journal(tmp_path, monkeypatch):
    append_conversation_event(tmp_path, "session-fast", "turn-1", EVENT_TURN_STARTED, status="running")
    journal_path = conversation_ledger_path(tmp_path, "session-fast")
    original_read_text = Path.read_text

    def fail_journal_read_text(path: Path, *args, **kwargs):
        if path == journal_path:
            raise AssertionError("append should not full-read turn_journal.jsonl for the next sequence")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_journal_read_text)

    append_conversation_event(
        tmp_path,
        "session-fast",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "second event"},
    )

    rows = [json.loads(line) for line in journal_path.open(encoding="utf-8") if line.strip()]
    assert [row["sequence"] for row in rows] == [1, 2]


def test_conversation_ledger_load_streams_journal_without_read_text(tmp_path, monkeypatch):
    append_conversation_event(tmp_path, "session-stream-load", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-stream-load",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "load should stream"},
    )
    journal_path = conversation_ledger_path(tmp_path, "session-stream-load")
    original_read_text = Path.read_text

    def fail_journal_read_text(path: Path, *args, **kwargs):
        if path == journal_path:
            raise AssertionError("load should stream turn_journal.jsonl instead of read_text().splitlines()")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_journal_read_text)

    events = load_conversation_events(tmp_path, "session-stream-load")

    assert [event.sequence for event in events] == [1, 2]


def test_conversation_ledger_preserves_interrupted_partial(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经完成前半部分。"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "process_restarted", "marker": TURN_INTERRUPTED_MARKER},
    )

    messages = conversation_model_messages_from_events(load_conversation_events(tmp_path, "session-a"))
    contents = [str(message.get("content") or "") for message in messages]

    assert "已经完成前半部分。" in contents
    assert any(TURN_INTERRUPTED_MARKER in content for content in contents)


def test_conversation_ledger_event_projection_categories_are_explicit():
    assert event_projection_category(EVENT_USER_MESSAGE) == "model"
    assert event_projection_category(EVENT_ASSISTANT_PARTIAL) == "volatile_model"
    assert event_projection_category(EVENT_TURN_STARTED) == "audit"
    assert event_projection_category(EVENT_TURN_COMPLETED) == "audit"
    assert event_projection_category("unknown_event") == "unknown"

    assert event_has_model_projection(EVENT_USER_MESSAGE) is True
    assert event_has_model_projection(EVENT_ASSISTANT_PARTIAL) is True
    assert event_has_model_projection(EVENT_TURN_COMPLETED) is False


def test_conversation_ledger_checkpoint_replaces_covered_history_for_model(tmp_path):
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-old",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "旧请求不应再逐条进入模型"},
    )
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-old",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-old", "name": "cli_tool", "status": "done", "result": "旧工具结果"}},
        tool_call_id="tool-old",
    )
    event = append_context_compression_checkpoint(
        tmp_path,
        "session-compress",
        turn_id="turn-new",
        current_turn_id="turn-new",
        summary="旧阶段已经完成：定位到压缩事实源分裂。",
        level="standard",
        reason="context_pressure",
        before_tokens=9000,
        after_tokens=3000,
        iteration=5,
        trigger_source="auto",
    )
    append_conversation_event(
        tmp_path,
        "session-compress",
        "turn-after",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "checkpoint 后的新请求应保留"},
    )

    messages = conversation_model_messages_from_events(load_conversation_events(tmp_path, "session-compress"))
    contents = "\n".join(str(message.get("content") or "") for message in messages)

    assert event is not None
    assert event.event_type == EVENT_COMPACTION_CHECKPOINT
    assert "旧阶段已经完成" in contents
    assert "checkpoint 后的新请求应保留" in contents
    assert "旧请求不应再逐条进入模型" not in contents
    assert "旧工具结果" not in contents
