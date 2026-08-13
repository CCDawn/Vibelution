"""Final-answer projection must not be replaced by orphan capture fragments."""

from __future__ import annotations

from core.web.services import session_service


def test_filter_drops_orphan_capture_fragments_but_keeps_commentary() -> None:
    final_answer = (
        "继续审查后的结论更明确：仅打开状态栏不会降低缓存命中率，"
        "也不会触发新的模型调用、Prompt 重组或 Provider 缓存键变化。"
    )
    events = [
        {
            "sequence": 1,
            "kind": "assistant_text",
            "status": "done",
            "content": "我会先定位状态栏实现与缓存键路径。",
            "source": "assistant_item_committed",
        },
        {
            "sequence": 2,
            "kind": "assistant_text",
            "status": "done",
            "content": "存。",
        },
        {
            "sequence": 3,
            "kind": "assistant_text",
            "status": "done",
            "content": "也不会触发新的模型调用、Prompt 重组或 Provider 缓存键变化。",
        },
        {
            "sequence": 4,
            "kind": "tool",
            "status": "done",
            "name": "read_file_tool",
            "summary": "读取状态栏实现",
        },
    ]

    filtered = session_service._filter_redundant_assistant_timeline_events(events, final_answer)

    assert [item["kind"] for item in filtered] == ["assistant_text", "tool"]
    assert filtered[0]["content"] == "我会先定位状态栏实现与缓存键路径。"
    assert filtered[0]["source"] == "assistant_item_committed"
    assert session_service._assistant_timeline_covers_final_content(filtered, final_answer) is False


def test_timeline_covers_final_content_when_answer_text_present() -> None:
    final_answer = "这是完整最终回答。"
    events = [
        {
            "sequence": 1,
            "kind": "assistant_text",
            "status": "done",
            "content": final_answer,
            "source": "assistant_item_committed",
        }
    ]
    assert session_service._assistant_timeline_covers_final_content(events, final_answer) is True
    assert session_service._assistant_timeline_covers_final_content([], final_answer) is False


def test_window_payload_attaches_explicit_final_answer_transcript() -> None:
    messages = session_service._normalize_messages(
        "session-window-final",
        [
            {
                "role": "user",
                "content": "继续",
                "timestamp": "2026-08-05T10:00:00Z",
            },
            {
                "role": "assistant",
                "content": "继续审查后的结论更明确：仅打开状态栏不会降低缓存命中率。",
                "timestamp": "2026-08-05T10:01:00Z",
                "metadata": {"turnId": "turn-window-final-1"},
            },
        ],
        transcript_scope="window",
    )
    assistant = next(item for item in messages if item["role"] == "assistant")
    # Phase A: turnItems is the UI package; transcript is one-way derived.
    turn_items = assistant["turnItems"]
    assert len(turn_items) >= 1
    final_items = [
        item
        for item in turn_items
        if str(item.get("phase") or "") == "final_answer"
        or (
            str(item.get("kind") or item.get("type") or "") in {"assistant_message", "agent_message"}
            and str(item.get("channel") or "") in {"", "answer"}
        )
    ]
    assert final_items
    expected_answer = "继续审查后的结论更明确：仅打开状态栏不会降低缓存命中率。"
    assert final_items[0]["text"] == expected_answer
    assert final_items[0].get("version") == 3
    assert final_items[0].get("itemId")
    assert final_items[0].get("terminal") is True

    assert "content" not in assistant
    assert "codexTranscript" not in assistant
    transcript = session_service._build_codex_transcript_from_turn_items(
        message_id=assistant["id"],
        turn_items=turn_items,
        streaming=False,
        window_slimmed=True,
    )
    assert transcript is not None
    assert transcript["source"] == "native"
    assert transcript.get("windowSlimmed") is True
    cells = transcript["cells"]
    assert len(cells) == 1
    assert cells[0]["kind"] == "assistant_markdown"
    assert cells[0]["phase"] == "final_answer"
    assert cells[0]["terminal"] is True
    assert cells[0]["text"] == expected_answer


def test_ui_projection_keeps_submission_anchor_on_committed_assistant() -> None:
    messages = session_service._normalize_messages(
        "session-anchor-1",
        [
            {
                "role": "user",
                "content": "检查一下",
                "timestamp": "2026-08-10T01:00:00Z",
                "metadata": {
                    "turnId": "turn-anchor-1",
                    "clientSubmissionId": "submission-anchor-1",
                },
            },
            {
                "role": "assistant",
                "content": "检查完成",
                "timestamp": "2026-08-10T01:00:01Z",
                "metadata": {
                    "kind": "assistant_item_committed",
                    "turnId": "turn-anchor-1",
                },
            },
        ],
        transcript_scope="window",
        include_timeline=False,
    )

    user, assistant = messages
    assert user["metadata"]["clientSubmissionId"] == "submission-anchor-1"
    assert assistant["metadata"]["turnId"] == "turn-anchor-1"
    assert assistant["metadata"]["clientSubmissionId"] == "submission-anchor-1"


def test_turn_items_projection_prefers_journal_and_stamps_message_id(monkeypatch) -> None:
    canonical = {
        "version": 2,
        "id": "item-final:0",
        "itemId": "item-final",
        "type": "assistant_message",
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "completed",
        "terminal": True,
        "provisional": False,
        "text": "来自 journal 的最终答案",
        "turnId": "turn-1",
        "sequence": 10,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(canonical)] if turn_id == "turn-1" else [],
    )
    items = session_service._build_session_turn_items_projection(
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-42",
        content="legacy text that must not win",
        done=True,
        source="session_detail",
    )
    assert len(items) == 1
    assert items[0]["text"] == "来自 journal 的最终答案"
    assert items[0]["version"] == 3
    assert items[0]["type"] == "agent_message"
    assert "messageId" not in items[0]
    assert items[0]["itemId"] == "item-final"


def test_turn_items_projection_merges_live_content_when_journal_has_tools_only(monkeypatch) -> None:
    """C3: tool-only journal package must still bridge streaming content onto same track."""
    tool_item = {
        "version": 2,
        "id": "tool-1:0",
        "itemId": "tool-1",
        "type": "tool_call",
        "kind": "tool_call",
        "phase": "tool_call",
        "status": "completed",
        "terminal": False,
        "provisional": False,
        "text": "read_file done",
        "toolName": "read_file_tool",
        "turnId": "turn-live-1",
        "sequence": 3,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(tool_item)] if turn_id == "turn-live-1" else [],
    )
    items = session_service._build_session_turn_items_projection(
        session_id="session-1",
        turn_id="turn-live-1",
        message_id="message-live-1",
        content="流式正文已经出现。",
        done=False,
        source="assistant_delta",
    )
    assert [item["type"] for item in items] == ["tool_call", "agent_message"]
    final_item = items[1]
    assert final_item["phase"] == "final_answer"
    assert final_item["text"] == "流式正文已经出现。"
    assert final_item["terminal"] is False
    assert final_item["status"] == "running"
    assert "messageId" not in final_item


def test_turn_items_projection_does_not_mirror_commentary_as_provisional_final(monkeypatch) -> None:
    """Live envelope content already committed as commentary must not become a second row."""
    commentary_text = "用户说刷新过了，但预算仍是 32，我需要查清策略来源。"
    commentary_item = {
        "version": 2,
        "id": "commentary-1:0",
        "itemId": "commentary-1",
        "type": "commentary",
        "kind": "commentary",
        "channel": "commentary",
        "phase": "commentary",
        "status": "completed",
        "terminal": False,
        "provisional": False,
        "text": commentary_text,
        "turnId": "turn-commentary-live-1",
        "sequence": 3,
        "revision": 0,
    }
    tool_item = {
        "version": 2,
        "id": "tool-commentary-1:0",
        "itemId": "tool-commentary-1",
        "type": "tool_call",
        "kind": "tool_call",
        "phase": "tool_call",
        "status": "completed",
        "terminal": False,
        "provisional": False,
        "text": "search done",
        "toolName": "search_tool",
        "turnId": "turn-commentary-live-1",
        "sequence": 4,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(commentary_item), dict(tool_item)]
        if turn_id == "turn-commentary-live-1"
        else [],
    )

    items = session_service._build_session_turn_items_projection(
        session_id="session-commentary-live-1",
        turn_id="turn-commentary-live-1",
        message_id="message-commentary-live-1",
        content=commentary_text,
        done=False,
        source="assistant_delta",
    )

    assert [(item["type"], item.get("phase")) for item in items] == [
        ("agent_message", "commentary"),
        ("tool_call", None),
    ]
    assert [item.get("text") for item in items].count(commentary_text) == 1
    assert not any(item.get("phase") == "final_answer" for item in items)


def test_turn_items_projection_keeps_distinct_live_final_after_commentary(monkeypatch) -> None:
    commentary_item = {
        "version": 2,
        "id": "commentary-distinct-1:0",
        "itemId": "commentary-distinct-1",
        "type": "commentary",
        "kind": "commentary",
        "channel": "commentary",
        "phase": "commentary",
        "status": "completed",
        "text": "我先检查配置来源。",
        "turnId": "turn-commentary-distinct-1",
        "sequence": 3,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(commentary_item)]
        if turn_id == "turn-commentary-distinct-1"
        else [],
    )

    items = session_service._build_session_turn_items_projection(
        session_id="session-commentary-distinct-1",
        turn_id="turn-commentary-distinct-1",
        message_id="message-commentary-distinct-1",
        content="最终确认：当前运行时读取的是 operator config。",
        done=False,
        source="assistant_delta",
    )

    assert [(item["type"], item.get("phase")) for item in items] == [
        ("agent_message", "commentary"),
        ("agent_message", "final_answer"),
    ]


def test_turn_items_projection_keeps_only_committed_final_when_commentary_matches(monkeypatch) -> None:
    duplicate_text = "最终确认：当前运行时读取的是 operator config。"
    commentary_item = {
        "version": 2,
        "id": "commentary-committed-1:0",
        "itemId": "commentary-committed-1",
        "type": "commentary",
        "kind": "commentary",
        "channel": "commentary",
        "phase": "commentary",
        "status": "completed",
        "text": duplicate_text,
        "turnId": "turn-commentary-committed-1",
        "sequence": 3,
        "revision": 0,
    }
    final_item = {
        "version": 2,
        "id": "final-committed-1:0",
        "itemId": "final-committed-1",
        "type": "assistant_message",
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "completed",
        "terminal": True,
        "provisional": False,
        "text": duplicate_text,
        "turnId": "turn-commentary-committed-1",
        "sequence": 4,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(commentary_item), dict(final_item)]
        if turn_id == "turn-commentary-committed-1"
        else [],
    )

    items = session_service._build_session_turn_items_projection(
        session_id="session-commentary-committed-1",
        turn_id="turn-commentary-committed-1",
        message_id="message-commentary-committed-1",
        content=duplicate_text,
        done=True,
        source="session_detail",
    )

    assert [(item["type"], item.get("phase"), item.get("text")) for item in items] == [
        ("agent_message", "final_answer", duplicate_text)
    ]


def test_turn_items_projection_merges_thought_when_journal_has_answer_only(monkeypatch) -> None:
    """Live/durable thought must survive journal final_answer package ownership."""
    answer = {
        "version": 2,
        "id": "item-final:0",
        "itemId": "item-final",
        "type": "assistant_message",
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "completed",
        "terminal": True,
        "provisional": False,
        "text": "你好！我是会话 Agent。",
        "turnId": "turn-thought-1",
        "sequence": 10,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(answer)] if turn_id == "turn-thought-1" else [],
    )
    thought = '用户只是打了个招呼"你好"。这是一个简单的问候，不需要调用任何工具。'
    items = session_service._build_session_turn_items_projection(
        session_id="session-1",
        turn_id="turn-thought-1",
        message_id="message-thought-1",
        content="你好！我是会话 Agent。",
        thought=thought,
        done=True,
        source="assistant_delta",
    )
    assert [item["type"] for item in items] == ["reasoning", "agent_message"]
    assert items[0]["text"] == thought
    assert "messageId" not in items[0]
    assert items[1]["text"] == "你好！我是会话 Agent。"
    assert items[1]["itemId"] == "item-final"

    transcript = session_service._build_codex_transcript_from_turn_items(
        message_id="message-thought-1",
        turn_items=items,
        streaming=False,
    )
    assert transcript is not None
    assert [cell["kind"] for cell in transcript["cells"]] == [
        "reasoning_summary",
        "assistant_markdown",
    ]
    assert transcript["cells"][0]["text"] == thought


def test_turn_items_projection_appends_new_reasoning_segment_after_prior_tool(monkeypatch) -> None:
    session_id = "session-segment-order"
    turn_id = "turn-segment-order"
    message_id = "message-segment-order"
    base_id = session_service._session_turn_item_base_id(session_id, turn_id)
    canonical = [
        {
            "itemId": f"{base_id}-reasoning-1",
            "type": "reasoning",
            "kind": "reasoning",
            "status": "completed",
            "text": "先检查日志。",
            "sequence": 10,
            "revision": 2,
        },
        {
            "itemId": "commentary-1",
            "type": "commentary",
            "kind": "commentary",
            "channel": "commentary",
            "phase": "commentary",
            "status": "completed",
            "text": "日志已读取，继续检查投影。",
            "sequence": 11,
            "revision": 0,
        },
        {
            "itemId": "tool-1",
            "type": "tool_call",
            "kind": "tool_call",
            "status": "completed",
            "callId": "call-read-log",
            "toolName": "read_log",
            "sequence": 12,
            "revision": 0,
        },
    ]
    transcript = {
        "cells": [
            {
                "id": f"{message_id}-feedback-1",
                "sourceItemId": f"{message_id}-feedback-1",
                "kind": "reasoning_summary",
                "status": "completed",
                "text": "先检查日志。",
                "sequence": 1,
                "revision": 2,
            },
            {
                "id": "tool-cell",
                "kind": "tool_call",
                "status": "completed",
                "callId": "call-read-log",
                "sequence": 2,
            },
            {
                "id": f"{message_id}-feedback-3",
                "sourceItemId": f"{message_id}-feedback-3",
                "kind": "reasoning_summary",
                "status": "running",
                "text": "再检查投影顺序。",
                "sequence": 3,
                "revision": 1,
            },
        ]
    }
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _session_id: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(item) for item in canonical],
    )

    items = session_service._build_session_turn_items_projection(
        session_id=session_id,
        turn_id=turn_id,
        message_id=message_id,
        thought="先检查日志。再检查投影顺序。",
        codex_transcript=transcript,
        done=False,
        source="session_live_overlay",
        stage="model_thinking",
    )

    assert [(item["type"], item.get("text")) for item in items] == [
        ("reasoning", "先检查日志。"),
        ("agent_message", "日志已读取，继续检查投影。"),
        ("tool_call", None),
        ("reasoning", "再检查投影顺序。"),
    ]
    assert items[-1]["itemId"].endswith("-reasoning-3")
    assert items[-1]["status"] == "running"


def test_turn_items_projection_extends_provisional_final_with_faster_content(monkeypatch) -> None:
    provisional = {
        "version": 2,
        "id": "answer:0",
        "itemId": "answer",
        "type": "assistant_message",
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "in_progress",
        "terminal": False,
        "provisional": True,
        "text": "你好",
        "turnId": "turn-1",
        "sequence": 1,
        "revision": 0,
    }
    monkeypatch.setattr(
        session_service,
        "_load_session_conversation_events_cached",
        lambda _session_id: [object()],
    )
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [dict(provisional)] if turn_id == "turn-1" else [],
    )
    items = session_service._build_session_turn_items_projection(
        session_id="session-1",
        turn_id="turn-1",
        message_id="message-stream",
        content="你好，世界",
        done=False,
        source="assistant_delta",
    )
    assert len(items) == 1
    assert items[0]["text"] == "你好，世界"
    assert items[0]["status"] == "running"
    assert items[0]["terminal"] is False


def test_window_slim_keeps_full_final_answer_text() -> None:
    long_answer = "最终结论：" + ("缓存命中率不受状态栏影响。" * 40)
    slim = session_service._slim_codex_transcript_for_window_payload(
        {
            "version": 1,
            "source": "native",
            "messageId": "message-1",
            "streaming": False,
            "cells": [
                {
                    "id": "final",
                    "kind": "assistant_markdown",
                    "messageId": "message-1",
                    "status": "completed",
                    "phase": "final_answer",
                    "terminal": True,
                    "text": long_answer,
                },
                {
                    "id": "tool",
                    "kind": "tool_call",
                    "messageId": "message-1",
                    "status": "completed",
                    "title": "read_file",
                    "text": "x" * 500,
                },
            ],
        }
    )
    assert slim is not None
    final_cell = next(cell for cell in slim["cells"] if cell["id"] == "final")
    tool_cell = next(cell for cell in slim["cells"] if cell["id"] == "tool")
    assert final_cell["text"] == long_answer
    assert final_cell["text"].endswith("…") is False
    assert tool_cell["text"].endswith("…")
    assert len(tool_cell["text"]) <= 401
