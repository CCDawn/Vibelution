"""Focused tests for session structure packs (publish/projection + Stage 2 slices)."""

from __future__ import annotations

from core.web.services import session_service as facade
from core.web.services.session import (
    agent_runtime,
    agent_sessions,
    cache_context,
    control,
    conversation_index,
    events,
    image_attachments,
    journal_bridge,
    list_cache,
    live_output,
    live_output_write,
    persist,
    projection,
    publish,
    schedule,
    session_ops,
    stream_capture,
    submit,
    timeline,
    turn_diagnostics,
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


def test_facade_reexports_conversation_index_pack() -> None:
    assert facade.create_chat_session is conversation_index.create_chat_session
    assert facade.ensure_agent_direct_session is conversation_index.ensure_agent_direct_session
    assert facade.query_sessions is conversation_index.query_sessions
    assert facade.select_chat_session is conversation_index.select_chat_session
    assert facade._ensure_conversation_agent_metadata is conversation_index._ensure_conversation_agent_metadata
    assert facade.repair_conversation_index_records is conversation_index.repair_conversation_index_records
    assert facade._repair_agent_direct_session_collisions is conversation_index._repair_agent_direct_session_collisions


def test_facade_reexports_live_output_write_pack() -> None:
    assert facade._set_session_live_output is live_output_write._set_session_live_output
    assert facade._set_session_llm_status_live_output is live_output_write._set_session_llm_status_live_output
    assert facade._set_session_turn_progress_live_output is live_output_write._set_session_turn_progress_live_output
    assert facade._build_live_output_message is live_output_write._build_live_output_message
    assert facade._live_output_checkpoint_payload is live_output_write._live_output_checkpoint_payload


def test_facade_reexports_timeline_pack() -> None:
    assert facade._build_turn_mental_snapshot is timeline._build_turn_mental_snapshot
    assert facade._normalize_persisted_tool_calls is timeline._normalize_persisted_tool_calls
    assert facade._normalize_persisted_feedback_events is timeline._normalize_persisted_feedback_events
    assert facade._assistant_timeline_events_by_turn is timeline._assistant_timeline_events_by_turn
    assert facade._persist_session_preflight_rejection is timeline._persist_session_preflight_rejection


def test_facade_reexports_turn_diagnostics_pack() -> None:
    assert facade.get_session_turn_completion_snapshot is turn_diagnostics.get_session_turn_completion_snapshot
    assert facade.create_chat_review_candidate_from_session is turn_diagnostics.create_chat_review_candidate_from_session
    assert facade._record_session_turn_error is turn_diagnostics._record_session_turn_error
    assert facade._persist_chat_turn_work_run is turn_diagnostics._persist_chat_turn_work_run
    assert facade._reconcile_stale_session_ledger is turn_diagnostics._reconcile_stale_session_ledger
    assert facade._resolve_session_references is turn_diagnostics._resolve_session_references


def test_facade_reexports_agent_runtime_pack() -> None:
    assert facade._acquire_chat_agent_for_session is agent_runtime._acquire_chat_agent_for_session
    assert facade._ensure_session_agent_prompt_snapshot is agent_runtime._ensure_session_agent_prompt_snapshot
    assert facade._session_agent_supports_image_input is agent_runtime._session_agent_supports_image_input
    assert facade._session_agent_runtime_cache_fingerprint is agent_runtime._session_agent_runtime_cache_fingerprint


def test_facade_reexports_cache_context_pack() -> None:
    assert facade._estimated_provider_prefix_cache_segments is cache_context._estimated_provider_prefix_cache_segments
    assert facade._aggregate_session_provider_cache_usage is cache_context._aggregate_session_provider_cache_usage
    assert facade._context_segment is cache_context._context_segment


def test_facade_reexports_image_attachments_pack() -> None:
    assert facade.store_session_image_artifact is image_attachments.store_session_image_artifact
    assert facade.store_session_user_image_attachment is image_attachments.store_session_user_image_attachment
    assert facade.resolve_session_image_artifact is image_attachments.resolve_session_image_artifact
    assert facade._build_llm_image_attachments is image_attachments._build_llm_image_attachments


def test_facade_reexports_events_pack() -> None:
    assert facade._record_session_turn_started_event is events._record_session_turn_started_event
    assert facade._record_session_turn_lifecycle_event is events._record_session_turn_lifecycle_event
    assert facade._record_session_list_loaded_event is events._record_session_list_loaded_event
    assert facade._record_session_list_prewarm_event is events._record_session_list_prewarm_event
    assert facade._record_session_message_edit_resubmit_event is events._record_session_message_edit_resubmit_event
    assert facade._record_session_delete_event is events._record_session_delete_event
    assert facade._record_session_guidance_event is events._record_session_guidance_event


def test_facade_reexports_session_ops_pack() -> None:
    assert facade.update_chat_session is session_ops.update_chat_session
    assert facade.update_chat_session_title is session_ops.update_chat_session_title
    assert facade.update_session_reasoning_effort is session_ops.update_session_reasoning_effort
    assert facade.prewarm_session_list_cache is session_ops.prewarm_session_list_cache
    assert facade.append_session_assistant_artifact_message is session_ops.append_session_assistant_artifact_message
    assert facade._repair_stale_running_conversations is session_ops._repair_stale_running_conversations
    assert facade._session_prompt_cache_partition is session_ops._session_prompt_cache_partition
    assert facade._make_chat_message is session_ops._make_chat_message
