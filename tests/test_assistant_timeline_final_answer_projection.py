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
    assert final_items[0]["text"] == assistant["content"]
    assert final_items[0].get("version") == 2
    assert final_items[0].get("itemId")
    assert final_items[0].get("terminal") is True

    transcript = assistant["codexTranscript"]
    assert transcript["source"] == "native"
    assert transcript.get("windowSlimmed") is True
    cells = transcript["cells"]
    assert len(cells) == 1
    assert cells[0]["kind"] == "assistant_markdown"
    assert cells[0]["phase"] == "final_answer"
    assert cells[0]["terminal"] is True
    assert cells[0]["text"] == assistant["content"]


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
    assert items[0]["messageId"] == "message-42"
    assert items[0]["itemId"] == "item-final"


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
