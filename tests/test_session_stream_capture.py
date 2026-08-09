"""Focused tests for session stream_capture slice."""

from __future__ import annotations

import threading

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
