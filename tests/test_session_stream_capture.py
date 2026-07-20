"""Focused tests for session stream_capture slice."""

from __future__ import annotations

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
