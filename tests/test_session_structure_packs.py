"""Focused tests for session structure packs (publish/projection + Stage 2 slices)."""

from __future__ import annotations

from core.web.services import session_service as facade
from core.web.services.session import (
    agent_sessions,
    control,
    journal_bridge,
    list_cache,
    live_output,
    persist,
    projection,
    publish,
    schedule,
    stream_capture,
    submit,
    worker,
)


def test_facade_reexports_publish_pack() -> None:
    assert facade.stream_session_events is publish.stream_session_events
    assert facade.get_session_stream_initial_state is publish.get_session_stream_initial_state
    assert facade._publish_session_detail_snapshot is publish._publish_session_detail_snapshot
    assert facade._publish_session_assistant_delta is publish._publish_session_assistant_delta
    assert facade._put_session_stream_event is publish._put_session_stream_event


def test_facade_reexports_projection_pack() -> None:
    assert facade.list_sessions is projection.list_sessions
    assert facade.get_session_detail is projection.get_session_detail
    assert facade.get_active_session_detail is projection.get_active_session_detail
    assert facade._build_session_summary is projection._build_session_summary
    assert facade._build_session_detail_from_summary is projection._build_session_detail_from_summary
    assert facade._normalize_conversation is projection._normalize_conversation
    assert facade._build_codex_transcript_projection is projection._build_codex_transcript_projection


def test_facade_reexports_stage2_hot_path_packs() -> None:
    assert facade.submit_session_message is submit.submit_session_message
    assert facade._schedule_session_turn is schedule._schedule_session_turn
    assert facade._run_session_turn is worker._run_session_turn
    assert facade._persist_session_turn_result is persist._persist_session_turn_result
    assert facade._capture_session_ui_stream is stream_capture._capture_session_ui_stream
    assert callable(facade._invalidate_session_list_cache)
    assert callable(list_cache.invalidate_session_list_cache)
    assert callable(live_output.snapshot_session_live_output)
    assert journal_bridge is not None


def test_facade_reexports_control_pack() -> None:
    assert facade.request_stop_session_turn is control.request_stop_session_turn
    assert facade._persist_session_interrupted_snapshot is control._persist_session_interrupted_snapshot
    assert facade._build_stopped_turn_result is control._build_stopped_turn_result


def test_facade_reexports_agent_sessions_pack() -> None:
    # Lifecycle-serialized surfaces wrap pack bodies on the facade.
    assert getattr(facade.stage_agent_session_purge, "__wrapped__", None) is agent_sessions.stage_agent_session_purge
    assert getattr(facade.commit_staged_agent_session_purge, "__wrapped__", None) is agent_sessions.commit_staged_agent_session_purge
    assert getattr(facade.archive_agent_sessions, "__wrapped__", None) is agent_sessions.archive_agent_sessions
    assert facade.create_child_session is agent_sessions.create_child_session
    assert facade.wake_agent_for_inbox_message is agent_sessions.wake_agent_for_inbox_message
    assert facade.append_cli_agent_lifecycle_event is agent_sessions.append_cli_agent_lifecycle_event
    assert facade.delete_chat_session is agent_sessions.delete_chat_session
