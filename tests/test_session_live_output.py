"""Focused tests for session live_output slice."""

from __future__ import annotations

from pathlib import Path

from core.web.services.session import live_output


def test_live_output_delta_append_and_replace() -> None:
    delta, replace = live_output.live_output_delta("hello", "hello world")
    assert delta == " world"
    assert replace is False

    delta, replace = live_output.live_output_delta("hello", "hi")
    assert delta == "hi"
    assert replace is True


def test_live_output_store_snapshot_clear_and_turn_guard() -> None:
    session_id = "live-output-test-session"
    live_output._SESSION_LIVE_OUTPUTS.pop(session_id, None)

    with live_output._SESSION_LIVE_OUTPUTS_LOCK:
        live_output._SESSION_LIVE_OUTPUTS[session_id] = live_output.SessionLiveOutputState(
            session_id=session_id,
            turn_id="turn-a",
            content="partial",
            thought="thinking",
        )

    snap = live_output.snapshot_session_live_output(session_id)
    assert snap is not None
    assert snap.content == "partial"
    assert snap.thought == "thinking"
    # defensive copy
    assert snap is not live_output._SESSION_LIVE_OUTPUTS[session_id]

    # wrong turn must not clear
    assert live_output.clear_session_live_output(session_id, turn_id="turn-b") is False
    assert live_output.snapshot_session_live_output(session_id) is not None

    assert live_output.clear_session_live_output(session_id, turn_id="turn-a") is True
    assert live_output.snapshot_session_live_output(session_id) is None


def test_live_output_checkpoint_visibility_and_roundtrip(tmp_path: Path) -> None:
    session_id = "ckpt-session"
    path = tmp_path / "live_output.json"

    empty = {"content": "", "thought": "", "toolCalls": [], "feedbackEvents": []}
    assert live_output.live_output_checkpoint_has_visible_payload(empty) is False
    assert live_output.live_output_checkpoint_has_assistant_payload(empty) is False

    state = live_output.SessionLiveOutputState(
        session_id=session_id,
        turn_id="turn-1",
        stage="model_request",
        content="hello",
        thought="plan",
        tool_calls=[{"id": "t1", "name": "read"}],
        feedback_events=[{"kind": "status", "name": "running"}],
        mental_snapshot={"focus": "x"},
        context_composition={"segments": []},
        llm_payload_trace={"requestId": "r1"},
        updated_at="2026-07-20T00:00:00Z",
    )
    payload = live_output.build_live_output_checkpoint_core_payload(
        state,
        updated_at=state.updated_at,
    )
    assert live_output.live_output_checkpoint_has_visible_payload(payload) is True
    assert live_output.live_output_checkpoint_has_assistant_payload(payload) is True
    assert "timelineItems" not in payload
    assert "codexTranscript" not in payload

    live_output.write_session_live_output_checkpoint(
        session_id,
        checkpoint_path=path,
        payload=payload,
        force=True,
    )
    assert path.is_file()

    loaded = live_output.load_session_live_output_checkpoint_payload(path)
    assert loaded is not None
    assert loaded["content"] == "hello"
    assert loaded["turnId"] == "turn-1"

    restored = live_output.state_from_checkpoint_payload(
        session_id,
        loaded,
        sanitize_thought=lambda value: str(value or "").strip(),
        sanitize_content=lambda value: str(value or "").strip(),
        normalize_mental_snapshot=lambda value: value if isinstance(value, dict) else None,
        normalize_tool_calls=lambda value: list(value or []) if isinstance(value, list) else [],
        normalize_feedback_events=lambda value: list(value or []) if isinstance(value, list) else [],
        normalize_context_composition=lambda value: value if isinstance(value, dict) else None,
        normalize_llm_payload_trace=lambda value: value if isinstance(value, dict) else None,
    )
    assert restored.content == "hello"
    assert restored.turn_id == "turn-1"
    assert restored.tool_calls[0]["id"] == "t1"

    live_output.discard_session_live_output_state(
        session_id,
        turn_id="turn-1",
        checkpoint_path=path,
    )
    assert not path.exists()
    assert live_output.snapshot_session_live_output(session_id) is None


def test_live_output_checkpoint_throttle_skips_rebuild(tmp_path: Path) -> None:
    session_id = "throttle-session"
    path = tmp_path / "live_output.json"
    calls = {"n": 0}

    def build_payload() -> dict:
        calls["n"] += 1
        return {
            "content": "x",
            "thought": "",
            "toolCalls": [],
            "feedbackEvents": [],
        }

    live_output.write_session_live_output_checkpoint(
        session_id,
        checkpoint_path=path,
        build_payload=build_payload,
        force=True,
        interval_seconds=60.0,
    )
    assert calls["n"] == 1
    assert path.is_file()

    live_output.write_session_live_output_checkpoint(
        session_id,
        checkpoint_path=path,
        build_payload=build_payload,
        force=False,
        interval_seconds=60.0,
    )
    # throttled: build_payload must not run again
    assert calls["n"] == 1
