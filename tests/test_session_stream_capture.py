"""Focused tests for session stream_capture slice."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from core.infrastructure.event_bus import EventNames, get_event_bus
from core.web.services import session_service
from core.web.services.session import stream_capture


def test_facade_reexports_stream_capture_symbols() -> None:
    assert session_service.SessionTurnCapture is stream_capture.SessionTurnCapture
    assert session_service._capture_session_ui_stream is stream_capture._capture_session_ui_stream
    assert session_service._ensure_session_ui_capture_hooks is stream_capture._ensure_session_ui_capture_hooks
    assert session_service._SESSION_UI_CAPTURE_CONTEXT is stream_capture._SESSION_UI_CAPTURE_CONTEXT


def test_session_turn_capture_thought_and_content() -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s1", turn_id="cap-t1")
    capture.note_thought("first thought chunk")
    assert "first thought chunk" in capture.thought
    assert any(item.get("kind") == "thought" for item in capture.feedback_events)

    capture.note_content("assistant body")
    assert capture.content == "assistant body"
    assert capture.uncommitted_content_segment() == "assistant body"
    capture.mark_content_committed()
    assert capture.uncommitted_content_segment() == ""


def test_reasoning_segments_commit_once_with_stable_identity_and_capture_order(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-order", turn_id="turn-order")
    capture.note_thought("先检查日志。")
    capture.note_tool_event("read_log", "done", call_id="call-read-log", result="ok")
    capture.note_thought("再检查投影顺序。")

    committed: list[dict] = []
    monkeypatch.setattr(session_service, "load_conversation_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [],
    )
    monkeypatch.setattr(
        session_service,
        "_append_session_conversation_event",
        lambda *_args, **kwargs: committed.append(dict(kwargs.get("payload") or {})),
    )
    monkeypatch.setattr(session_service, "_invalidate_session_conversation_events_cache", lambda _session_id: None)

    assert stream_capture._commit_session_capture_reasoning_segments(
        "cap-order",
        capture,
        source="test_capture_order",
    ) == 2
    assert [item["text"] for item in committed] == ["先检查日志。", "再检查投影顺序。"]
    assert [item["sequence"] for item in committed] == [1, 3]
    assert committed[0]["itemId"].endswith("-reasoning-1")
    assert committed[1]["itemId"].endswith("-reasoning-3")
    assert all(item["status"] == "completed" for item in committed)

    assert stream_capture._commit_session_capture_reasoning_segments(
        "cap-order",
        capture,
        source="test_capture_order",
    ) == 0
    assert len(committed) == 2


def test_llm_response_commits_reasoning_before_protocol_outcome(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-llm-order", turn_id="turn-llm-order")
    calls: list[str] = []
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)
    monkeypatch.setattr(session_service, "load_conversation_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id="": [],
    )
    monkeypatch.setattr(
        session_service,
        "_append_session_conversation_event",
        lambda *_args, **_kwargs: calls.append("reasoning"),
    )
    monkeypatch.setattr(
        session_service,
        "append_conversation_turn_outcome",
        lambda *_args, **_kwargs: calls.append("outcome"),
    )
    monkeypatch.setattr(session_service, "_invalidate_session_conversation_events_cache", lambda _session_id: None)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)

    with stream_capture._capture_session_ui_stream("cap-llm-order", capture):
        capture.note_thought("先形成推理片段。")
        get_event_bus().publish(
            EventNames.LLM_RESPONSE,
            {"turn_outcome": SimpleNamespace(events=())},
        )

    assert calls[:2] == ["reasoning", "outcome"]


def test_text_batcher_done_flushes_response(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s2", turn_id="cap-t2")
    published: list[dict] = []

    def fake_set(session_id, **kwargs):
        published.append({"session_id": session_id, **kwargs})

    monkeypatch.setattr(session_service, "_set_session_live_output", fake_set)
    batcher = stream_capture._SessionUiCaptureTextBatcher(session_id="cap-s2", capture=capture)
    batcher.note_response("streamed assistant text", done=True)
    assert published
    assert published[-1]["session_id"] == "cap-s2"
    assert "streamed assistant text" in str(published[-1].get("content") or "")


def test_stream_response_preserves_delta_whitespace_and_newlines(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-whitespace", turn_id="turn-whitespace")
    published: list[dict] = []
    ui = SimpleNamespace(
        stream_response=lambda *_args, **_kwargs: None,
        clear_response_stream=lambda: None,
        stream_thought=lambda *_args, **_kwargs: None,
        clear_thought_stream=lambda: None,
        set_pet_mental_state=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda session_id, **kwargs: published.append({"sessionId": session_id, **kwargs}))

    with stream_capture._capture_session_ui_stream("cap-whitespace", capture):
        ui.stream_response("Hello", done=False)
        ui.stream_response(" world", done=False)
        ui.stream_response("\nnext line", done=False)

    assert capture.content == "Hello world\nnext line"
    assert published[-1]["content"] == "Hello world\nnext line"


def test_stream_response_repeated_delta_is_not_deduplicated(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-repeat", turn_id="turn-repeat")
    ui = SimpleNamespace(
        stream_response=lambda *_args, **_kwargs: None,
        clear_response_stream=lambda: None,
        stream_thought=lambda *_args, **_kwargs: None,
        clear_thought_stream=lambda: None,
        set_pet_mental_state=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)

    with stream_capture._capture_session_ui_stream("cap-repeat", capture):
        ui.stream_response("a", done=False)
        ui.stream_response("a", done=False)
        ui.stream_response("aa", done=True)

    assert capture.content == "aa"


def test_stream_response_done_replaces_draft_with_authoritative_text(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-revision", turn_id="turn-revision")
    ui = SimpleNamespace(
        stream_response=lambda *_args, **_kwargs: None,
        clear_response_stream=lambda: None,
        stream_thought=lambda *_args, **_kwargs: None,
        clear_thought_stream=lambda: None,
        set_pet_mental_state=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)

    with stream_capture._capture_session_ui_stream("cap-revision", capture):
        ui.stream_response("draft", done=False)
        ui.stream_response("final revised", done=True)

    assert capture.content == "final revised"


def test_stream_response_repeated_final_does_not_append(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-final", turn_id="turn-final")
    ui = SimpleNamespace(
        stream_response=lambda *_args, **_kwargs: None,
        clear_response_stream=lambda: None,
        stream_thought=lambda *_args, **_kwargs: None,
        clear_thought_stream=lambda: None,
        set_pet_mental_state=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: ui)
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *_args, **_kwargs: None)

    with stream_capture._capture_session_ui_stream("cap-final", capture):
        ui.stream_response("final", done=True)
        ui.stream_response("final", done=True)

    assert capture.content == "final"

def test_tool_start_with_explicit_turn_identity_survives_thread_boundary(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3", turn_id="cap-t3")
    published: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_set_session_live_output",
        lambda session_id, **kwargs: published.append({"sessionId": session_id, **kwargs}),
    )
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", lambda **kwargs: None)

    def publish_from_worker() -> None:
        get_event_bus().publish(EventNames.TOOL_START, {
            "name": "glob_tool",
            "callId": "call-threaded",
            "sessionId": "cap-s3",
            "turnId": "cap-t3",
            "args": {"pattern": "**/*.py"},
        })

    with stream_capture._capture_session_ui_stream("cap-s3", capture):
        worker = threading.Thread(target=publish_from_worker)
        worker.start()
        worker.join(timeout=5)

    assert capture.tool_calls[0]["callId"] == "call-threaded"
    assert capture.tool_calls[0]["status"] == "running"
    assert published[-1]["tool_calls"][0]["callId"] == "call-threaded"


def test_tool_start_revisions_update_one_live_record(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3b", turn_id="cap-t3b")
    published: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_set_session_live_output",
        lambda session_id, **kwargs: published.append({"sessionId": session_id, **kwargs}),
    )
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", lambda **kwargs: None)

    with stream_capture._capture_session_ui_stream("cap-s3b", capture):
        for payload in (
            {
                "name": "glob_tool",
                "lifecyclePhase": "started",
                "eventAtEpochMs": 1_786_294_801_125,
            },
            {"name": "glob_tool", "lifecyclePhase": "arguments_ready", "args": {"pattern": "**/*.py"}},
        ):
            get_event_bus().publish(EventNames.TOOL_START, {
                **payload,
                "callId": "call-revision",
                "sessionId": "cap-s3b",
                "turnId": "cap-t3b",
            })

    assert len(capture.tool_calls) == 1
    assert capture.tool_calls[0]["revision"] == 1
    assert capture.tool_calls[0]["arguments"] == {"pattern": "**/*.py"}
    assert capture.tool_calls[0]["executionStartedAtEpochMs"] == 1_786_294_801_125
    assert published[-1]["tool_calls"][0]["revision"] == 1
    assert published[-1]["tool_calls"][0]["executionStartedAtEpochMs"] == 1_786_294_801_125
    transcript = session_service._build_codex_transcript_projection(
        message_id="message-live",
        feedback_events=capture.feedback_events,
        tool_calls=capture.tool_calls,
        streaming=True,
    )
    turn_items = session_service._build_session_turn_items_projection(
        session_id="cap-s3b",
        turn_id="cap-t3b",
        message_id="message-live",
        codex_transcript=transcript,
        done=False,
        source="session_live_overlay",
    )
    tool_item = next(item for item in turn_items if item["type"] == "tool_call")
    assert tool_item["metadata"]["executionStartedAtEpochMs"] == 1_786_294_801_125


def test_live_tool_start_metadata_enriches_existing_journal_item(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3b", turn_id="cap-t3b")
    capture.note_tool_event(
        "glob_tool",
        "running",
        call_id="call-revision",
        event_at_epoch_ms=1_786_294_801_125,
    )
    transcript = session_service._build_codex_transcript_projection(
        message_id="message-live",
        feedback_events=capture.feedback_events,
        tool_calls=capture.tool_calls,
        streaming=True,
    )
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _session_id: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id: [
            {
                "id": "journal-tool:0",
                "itemId": "journal-tool",
                "version": 3,
                "sessionId": "cap-s3b",
                "turnId": turn_id,
                "type": "tool_call",
                "status": "running",
                "revision": 0,
                "sequence": 1,
                "callId": "call-revision",
                "toolName": "glob_tool",
            }
        ],
    )

    turn_items = session_service._build_session_turn_items_projection(
        session_id="cap-s3b",
        turn_id="cap-t3b",
        message_id="message-live",
        codex_transcript=transcript,
        done=False,
        source="assistant_delta",
    )

    tool_item = next(item for item in turn_items if item["type"] == "tool_call")
    assert tool_item["metadata"]["executionStartedAtEpochMs"] == 1_786_294_801_125


def test_live_tool_start_appends_call_missing_from_cached_journal(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3b", turn_id="cap-t3b")
    capture.note_tool_event(
        "grep_search_tool",
        "running",
        call_id="call-new",
        event_at_epoch_ms=1_786_294_801_125,
    )
    transcript = session_service._build_codex_transcript_projection(
        message_id="message-live",
        feedback_events=capture.feedback_events,
        tool_calls=capture.tool_calls,
        streaming=True,
    )
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda _session_id: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda _events, *, turn_id: [
            {
                "id": "journal-tool:0",
                "itemId": "journal-tool",
                "version": 3,
                "sessionId": "cap-s3b",
                "turnId": turn_id,
                "type": "tool_call",
                "status": "completed",
                "revision": 0,
                "sequence": 1,
                "callId": "call-existing",
                "toolName": "glob_tool",
            }
        ],
    )

    turn_items = session_service._build_session_turn_items_projection(
        session_id="cap-s3b",
        turn_id="cap-t3b",
        message_id="message-live",
        codex_transcript=transcript,
        done=False,
        source="assistant_delta",
    )

    assert [item["callId"] for item in turn_items if item["type"] == "tool_call"] == [
        "call-existing",
        "call-new",
    ]
    live_item = next(item for item in turn_items if item.get("callId") == "call-new")
    assert live_item["status"] == "running"
    assert live_item["metadata"]["executionStartedAtEpochMs"] == 1_786_294_801_125


def test_explicit_wrong_turn_is_dropped_even_inside_capture_context(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3c", turn_id="cap-t3c")
    discarded: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *_args, **kwargs: discarded.append(kwargs),
    )

    with stream_capture._capture_session_ui_stream("cap-s3c", capture):
        get_event_bus().publish(EventNames.TOOL_START, {
            "name": "glob_tool",
            "callId": "call-wrong-turn",
            "sessionId": "cap-s3c",
            "turnId": "other-turn",
        })

    assert capture.tool_calls == []
    assert discarded[-1]["fields"]["reason"] == "turn_mismatch"


def test_repeated_wrong_turn_discards_are_recorded_only_once(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s3d", turn_id="cap-t3d")
    discarded: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *_args, **kwargs: discarded.append(kwargs),
    )

    with stream_capture._capture_session_ui_stream("cap-s3d", capture):
        for _ in range(3):
            get_event_bus().publish(EventNames.TOOL_START, {
                "name": "glob_tool",
                "callId": "call-wrong-turn",
                "sessionId": "cap-s3d",
                "turnId": "other-turn",
            })

    assert capture.tool_calls == []
    assert len(discarded) == 1
    assert discarded[0]["fields"]["reason"] == "turn_mismatch"


def test_tool_lifecycle_keeps_sequence_and_increments_revision() -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s4", turn_id="cap-t4")

    capture.note_tool_event("grep_search_tool", "running", call_id="call-1", arguments={"query": "needle"})
    running = dict(capture.feedback_events[-1])
    capture.note_tool_event("grep_search_tool", "completed", "found", call_id="call-1", result="found")
    completed = capture.feedback_events[-1]

    assert completed["callId"] == running["callId"] == "call-1"
    assert completed["sequence"] == running["sequence"]
    assert running["revision"] == 0
    assert completed["revision"] == 1

    capture.note_tool_event("grep_search_tool", "completed", "found again", call_id="call-1", result="found again")
    assert len(capture.tool_calls) == 1
    assert capture.tool_calls[0]["revision"] == 2
    assert capture.feedback_events[-1]["sequence"] == running["sequence"]
    assert capture.feedback_events[-1]["revision"] == 2


def test_live_tool_event_without_call_id_is_dropped_with_reason(monkeypatch) -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-s5", turn_id="cap-t5")
    discarded: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *_args, **kwargs: discarded.append(kwargs),
    )

    with stream_capture._capture_session_ui_stream("cap-s5", capture):
        get_event_bus().publish(EventNames.TOOL_START, {
            "name": "glob_tool",
            "sessionId": "cap-s5",
            "turnId": "cap-t5",
        })

    assert capture.tool_calls == []
    assert discarded[-1]["fields"]["reason"] == "call_id_missing"


def test_tool_arguments_keep_bounded_patch_text_for_diff_rendering() -> None:
    capture = stream_capture.SessionTurnCapture(session_id="cap-patch", turn_id="cap-t-patch")
    patch_text = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: demo.py",
            "@@",
            "-value = 1",
            "+value = 2",
            *[f"+padding line {index} {'x' * 80}" for index in range(10)],
            "*** End Patch",
        ]
    )
    assert len(patch_text) > 420

    capture.note_tool_event(
        "apply_patch_tool",
        "completed",
        call_id="call-patch",
        arguments={"patch_text": patch_text, "api_key": "must-not-leak"},
    )
    transcript = session_service._build_codex_transcript_projection(
        message_id="message-patch",
        feedback_events=capture.feedback_events,
        tool_calls=capture.tool_calls,
        streaming=False,
    )

    arguments = transcript["toolCalls"][0]["arguments"]
    assert arguments["patch_text"] == patch_text
    assert "api_key" not in arguments


def test_successful_tool_records_progress_before_live_projection(monkeypatch):
    capture = stream_capture.SessionTurnCapture(session_id="progress-s", turn_id="progress-t")
    order = []
    monkeypatch.setattr(session_service, "_append_session_conversation_event", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "_touch_chat_turn_work_run", lambda **kw: order.append(("progress", kw)))
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *a, **kw: order.append(("projection", kw)))
    with stream_capture._capture_session_ui_stream("progress-s", capture):
        get_event_bus().publish(EventNames.TOOL_SUCCESS, {"name": "batch_web_search_tool",
            "callId": "progress-call", "sessionId": "progress-s", "turnId": "progress-t", "result": "found"})
    assert [item[0] for item in order][:2] == ["progress", "projection"]
    assert order[0][1] == {"session_id": "progress-s", "turn_id": "progress-t", "stage": "tool_result"}


def _publish_stream_restart(session_id: str, turn_id: str, attempt: int = 2) -> None:
    get_event_bus().publish(
        EventNames.LLM_STATUS,
        {
            "status": "retrying",
            "streamRestart": attempt,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    )


def test_stream_restart_marker_resets_partial_boundaries(monkeypatch) -> None:
    """restart 标记清空进行中边界，重试 attempt 的内容不拼在失败残段之后。"""

    capture = stream_capture.SessionTurnCapture(session_id="restart-s", turn_id="restart-t")
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "_set_session_llm_status_live_output", lambda *a, **kw: None)

    with stream_capture._capture_session_ui_stream("restart-s", capture):
        capture.note_thought("失败 attempt 的部分推理。")
        capture.note_content("失败 attempt 的部分回答")
        assert capture.thought and capture.content
        assert [item for item in capture.feedback_events if item.get("kind") == "thought"]

        _publish_stream_restart("restart-s", "restart-t")

        assert capture.thought == ""
        assert capture.content == ""
        assert capture.uncommitted_content_segment() == ""
        assert not [item for item in capture.feedback_events if item.get("kind") == "thought"]

        # 重试 attempt 的重生成内容从干净边界写入，不与失败残段拼接
        capture.note_content("重试 attempt 的完整回答")
        assert capture.content == "重试 attempt 的完整回答"
        capture.note_thought("重试 attempt 的推理。")
        thoughts = [item for item in capture.feedback_events if item.get("kind") == "thought"]
        assert len(thoughts) == 1
        assert thoughts[0]["resultPreview"] == "重试 attempt 的推理。"


def test_stream_restart_marker_drops_stale_running_tool_calls(monkeypatch) -> None:
    """失败 attempt 发出的 running 工具条目被摘除；已完成工具与对应历史保留。"""

    capture = stream_capture.SessionTurnCapture(session_id="restart-tool-s", turn_id="restart-tool-t")
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "_set_session_llm_status_live_output", lambda *a, **kw: None)

    with stream_capture._capture_session_ui_stream("restart-tool-s", capture):
        capture.note_tool_event("read_log", "done", call_id="call-done", result="ok")
        capture.note_tool_event("web_search", "running", call_id="call-stale")

        _publish_stream_restart("restart-tool-s", "restart-tool-t")

        call_ids = [str(item.get("callId") or "") for item in capture.tool_calls]
        assert call_ids == ["call-done"]
        stale_feedback = [
            item
            for item in capture.feedback_events
            if item.get("kind") == "tool" and str(item.get("callId") or "") == "call-stale"
        ]
        assert not stale_feedback
        kept_feedback = [
            item
            for item in capture.feedback_events
            if item.get("kind") == "tool" and str(item.get("callId") or "") == "call-done"
        ]
        assert kept_feedback


def test_stream_restart_marker_failure_does_not_break_capture(monkeypatch) -> None:
    """restart 处理抛错不得外溢：流继续，后续内容仍按既有语义写入 capture。"""

    capture = stream_capture.SessionTurnCapture(session_id="restart-err-s", turn_id="restart-err-t")
    monkeypatch.setattr(session_service, "_set_session_live_output", lambda *a, **kw: None)
    monkeypatch.setattr(session_service, "_set_session_llm_status_live_output", lambda *a, **kw: None)

    def broken_reset(*_args, **_kwargs):
        raise RuntimeError("reset failed")

    monkeypatch.setattr(stream_capture, "_reset_capture_stream_restart_boundary", broken_reset)

    with stream_capture._capture_session_ui_stream("restart-err-s", capture):
        capture.note_content("失败 attempt 的部分回答")
        _publish_stream_restart("restart-err-s", "restart-err-t")
        capture.note_content("失败 attempt 的部分回答（追加）")
        assert capture.content == "失败 attempt 的部分回答（追加）"


def test_evicted_thought_events_survive_for_commit() -> None:
    """120 条上限逐出的未提交 thought 段必须仍能被 uncommitted 消费到。"""
    capture = stream_capture.SessionTurnCapture(session_id="cap-evict", turn_id="turn-evict")
    thought_entry = {"kind": "thought", "status": "ok", "name": "reason", "resultPreview": "early reasoning"}
    capture._append_feedback_event(dict(thought_entry))
    for index in range(130):
        capture._append_feedback_event(
            {"kind": "tool", "status": "ok", "name": f"tool-{index}", "summary": "x"}
        )

    assert len(capture.feedback_events) == 120
    uncommitted = capture.uncommitted_thought_events()
    assert uncommitted, "evicted thought segment must stay visible to the commit path"
    assert uncommitted[0]["resultPreview"] == "early reasoning"
    capture.mark_thought_events_committed(uncommitted[0]["sequence"])
    assert capture.uncommitted_thought_events() == []
