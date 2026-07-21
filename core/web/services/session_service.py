"""Real chat session payloads for the web workbench."""

# Extracted session modules intentionally late-bind compatibility symbols from
# this facade through _service(); those imports are public injection points.
# ruff: noqa: F401

from __future__ import annotations

import base64
import binascii
import copy
import json
import os
import queue
import re
import secrets
import shutil
import stat
import threading
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from config.llm_key_env import sync_llm_key_env_from_persisted_user_env
from config.settings import get_config
from core.context.segments import (
    build_context_manifest,
    build_context_segment,
    normalize_context_manifest,
)
from core.context.skill_contract import (
    build_active_skill_contract,
    build_active_skill_runtime_context,
    normalize_active_skill_contract,
    refresh_active_skill_contract_status,
)
from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.chat_result_formatter import format_chat_reply
from core.chat.chat_task_types import trim_lines
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_conversation_event,
    append_conversation_turn_outcome,
    conversation_ledger_path,
    conversation_visible_messages_from_events,
    conversation_turn_items_from_events,
    latest_ledger_sequence,
    latest_open_turn_id,
    load_conversation_events,
    rewrite_conversation_events,
)
from core.chat.context_assembler import assemble_conversation_context
from core.chat.skill_registry import build_skill_runtime_context, skill_descriptor_for_log
from core.chat.slash_commands import SkillSlashCommand, parse_skill_slash_command
from core.infrastructure import developer_sandbox
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.infrastructure.feature_gate import (
    resolve_feature_decision,
)
from core.llm.client import llm_status_context
from core.llm.agent_runtime import (
    AgentLlmResolutionError,
    resolve_agent_llm,
)
from core.llm.reasoning_effort import normalize_reasoning_effort
from core.infrastructure.tool_result import infer_tool_business_success
from core.mental_model_flags import is_mental_model_enabled
from core.evaluation.chat_dataset_capture import ChatDatasetCaptureService
from core.evaluation.chat_next_state_signals import (
    append_chat_next_state_signal,
    list_chat_next_state_signals,
    summarize_chat_next_state_signals,
)
from core.evaluation.chat_segmenter import ChatTurnRecord, has_conclusion_signal, has_next_action_signal
from core.logging.logger import debug as _debug_logger
from core.logging.unified_logger import logger as unified_logger
from core.mental_model_flags import mental_model_enabled_override
from core.orchestration.output_boundary import (
    sanitize_assistant_thought_delta_text,
    sanitize_assistant_thought_text,
    sanitize_assistant_visible_text,
)
from core.orchestration.cache_diagnostics import compact_repeated_metadata_text
from core.orchestration.context_engine import build_agent_context, record_agent_turn_result
from core.orchestration.turn_runner import (
    call_agent_factory_with_supported_kwargs,
    create_agent_runtime,
    run_existing_agent_single_turn,
)
from core.runtime_manager.evolution_store import load_active_run_snapshot as load_evolution_active_run_snapshot
from core.runtime_manager.work_run_leases import (
    MEMORY_WRITE_LEASE,
    SUPERVISED_EVALUATION_CHAT_LEASE,
    WORKTREE_WRITE_LEASE,
    WorkRunLeaseRequest,
    check_lease_conflicts,
    infer_chat_turn_leases,
    leases_for_snapshot,
    normalize_leases,
)
from core.runtime_manager.work_run_store import WorkRunStore
from tools.session_reference_tools import session_reference_context
from core.ui.chat_state import (
    CHAT_STATE_VERSION,
    DEFAULT_CHAT_CONVERSATION_ID,
    DEFAULT_CHAT_CONVERSATION_TITLE,
    chat_state_transaction,
    chat_state_path,
    load_chat_state,
    normalize_chat_attachments,
    normalize_chat_messages,
    normalize_chat_tool_calls,
    save_chat_state,
)

from . import agent_directory_service
from .conversation_timeline_service import build_conversation_timeline_items
from .i18n import get_web_language, text_for
from .model_capability_service import model_record_image_input_support
from . import prompt_template_service
from .session_turn_scheduler import SessionTurnScheduler
from .agent_directory_service import (
    AgentNotFoundError,
    active_agent_runtime,
    agent_dialogue_model_id,
    agent_llm_model_id,
    consume_agent_inbox_message,
    ensure_agent_for_session,
    evaluate_agent_workspace_write,
    evaluate_delegation_wake_policy,
    get_agent,
    list_agent_inbox_messages_for_agent,
    list_group_context_events_for_agent,
    next_wakeable_agent_inbox_message_for_agent,
    resolve_memory_policy_for_agent,
    update_agent_instance,
)
from .runtime_scene_service import record_runtime_scene_conversation_event, record_runtime_scene_event
from .session.list_cache import (
    SESSION_LIST_CACHE_TTL_SECONDS as _SESSION_LIST_CACHE_TTL_SECONDS,
    _begin_session_list_cache_build,
    _copy_session_list_snapshot,
    _copy_session_summary_snapshot,
    _finish_session_list_cache_build,
    _get_session_list_cache,
    _get_session_list_cache_locked,
    _session_list_source_signature,
    _set_session_list_cache,
    invalidate_session_list_cache as _invalidate_session_list_cache_core,
)
from .session.live_output import (
    SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS as _SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS,
    SessionLiveOutputState,
    # Re-export store/checkpoint symbols for tests/helpers that touch session_service._SESSION_LIVE_*.
    _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT,
    _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK,
    _SESSION_LIVE_OUTPUTS,
    _SESSION_LIVE_OUTPUTS_LOCK,
    build_live_output_checkpoint_core_payload,
    clear_session_live_output as _clear_session_live_output_memory,
    delete_session_live_output_checkpoint as _delete_session_live_output_checkpoint_core,
    discard_session_live_output_state as _discard_session_live_output_state_core,
    live_output_checkpoint_has_assistant_payload as _live_output_checkpoint_has_assistant_payload,
    live_output_checkpoint_has_visible_payload as _live_output_checkpoint_has_visible_payload,
    live_output_delta as _live_output_delta,
    load_session_live_output_checkpoint_payload as _load_session_live_output_checkpoint_payload,
    snapshot_session_live_output as _snapshot_session_live_output,
    state_from_checkpoint_payload as _state_from_checkpoint_payload,
    write_session_live_output_checkpoint as _write_session_live_output_checkpoint_core,
)
from .session import journal_bridge as _journal_bridge
from .session.submit import (
    _accepted_session_turn_payload,
    _resolve_user_message_content,
    edit_and_resubmit_session_message,
    submit_session_guidance,
    submit_session_message,
    submit_session_message_lightweight,
)
from .session.schedule import (
    _cancel_queued_scheduler_context,
    _cancel_queued_session_turn,
    _drain_wakeable_agent_inbox_after_session_release,
    _execute_scheduled_session_turn,
    _mark_session_turn_dequeued,
    _mark_session_turn_queued,
    _record_scheduler_event_adapter,
    _record_session_scheduler_event,
    _release_scheduled_session_turn,
    _schedule_session_turn,
    _scheduler_context_is_external,
    _scheduler_log_fields,
    _session_scheduler_agent_key,
    _session_scheduler_session_key,
    _submit_released_session_turn,
    _submit_scheduled_session_turn,
    cancel_agent_execution_reservation,
    reserve_agent_execution_slot,
)
from .session.stream_capture import (
    SessionTurnCapture,
    _SESSION_UI_CAPTURE_CONTEXT,
    _SESSION_UI_CAPTURE_LOCK,
    _SESSION_UI_CAPTURE_RESPONSE_BATCH_LATENCY_MIN_CHARS,
    _SESSION_UI_CAPTURE_RESPONSE_BATCH_MAX_LATENCY_SECONDS,
    _SESSION_UI_CAPTURE_RESPONSE_BATCH_MIN_CHARS,
    _SESSION_UI_CAPTURE_THOUGHT_BATCH_LATENCY_MIN_CHARS,
    _SESSION_UI_CAPTURE_THOUGHT_BATCH_MAX_LATENCY_SECONDS,
    _SESSION_UI_CAPTURE_THOUGHT_BATCH_MIN_CHARS,
    _SessionUiCaptureTextBatcher,
    _active_session_turn_capture,
    _attach_turn_capture_to_result,
    _capture_session_ui_stream,
    _commit_session_capture_assistant_segment,
    _ensure_session_ui_capture_hooks,
    _seed_capture_from_live_feedback_events,
)
from .session.worker import (
    _run_session_continuation_loop,
    _run_session_turn,
    _session_context_allows_internal_auto_continue,
    _session_context_internal_auto_continue_max_turns,
)
from .session.persist import (
    _ensure_session_turn_terminal_fallback,
    _persist_session_turn_failure,
    _persist_session_turn_result,
    _persist_session_turn_runtime_error,
)
from core.web.services.session.control import (
    request_stop_session_turn,
    _persist_session_interrupted_snapshot,
    _append_stale_turn_interruption_if_session_inactive,
    _build_auto_continue_paused_result,
    _build_stopped_turn_result,
)
from core.web.services.session.agent_sessions import (
    stage_agent_session_purge,
    commit_staged_agent_session_purge,
    restore_staged_agent_session_purge,
    retry_pending_agent_session_purge_cleanup,
    agent_session_purge_cleanup_failure_result,
    archive_agent_sessions,
    restore_agent_sessions_archive,
    create_child_session,
    list_child_sessions,
    create_supervised_agent_session,
    delete_chat_session,
    delete_chat_session_lightweight,
    reset_agent_direct_session_lightweight,
    mark_direct_session_agent_deleted,
    restore_direct_session_agent_deleted_tombstone,
    wake_agent_for_inbox_message,
    recover_wakeable_agent_inbox_messages_on_startup,
    append_cli_agent_lifecycle_event,
    append_cli_agent_task_result_event,
    _delete_chat_session_state,
    _agent_session_conversation_ids,
    _agent_session_lifecycle_restore_token,
    _agent_session_purge_cleanup_marker_path,
    _agent_session_purge_manifest_path,
    _agent_session_purge_staging_root,
    _agent_session_purge_staging_root_is_safe,
    _agent_session_workspace_roots,
    _delete_agent_session_purge_staging_root,
    _write_agent_session_purge_manifest,
    _write_agent_session_purge_record,
    _read_agent_session_purge_cleanup_marker,
    _read_agent_session_purge_manifest,
    _restore_agent_session_lifecycle_state,
    _restore_staged_agent_workspace_move,
    _replacement_session_after_agent_session_removal,
    _ensure_agent_direct_session_not_reassigned,
    _safe_session_workspace_token,
    _record_agent_session_lifecycle_event,
    _record_direct_session_agent_deleted_event,
    _record_direct_session_agent_deleted_rollback_event,
    _child_session_created_card,
    _child_session_initial_prompt,
    _record_child_session_event,
    _raw_conversation_child_session_ids,
    _wake_agent_for_cli_agent_task_result,
    _format_cli_agent_task_result_content,
    _find_cli_agent_lifecycle_message,
    _find_cli_agent_task_result_message,
    _record_cli_agent_lifecycle_event,
    _record_cli_agent_task_result_event,
    _deliver_agent_inbox_turn_reply,
    _build_agent_inbox_turn_reply,
    _agent_inbox_message_from_kernel_delivery,
    _agent_inbox_kernel_delivery,
    _agent_inbox_reply_kernel_metadata,
    _agent_inbox_auto_reply_skip_reason,
    _is_agent_inbox_message_entry,
    _latest_agent_inbox_user_message,
    _looks_like_agent_inbox_protocol_message,
    _format_agent_inbox_wake_prompt,
    _record_agent_inbox_reply_event,
    _record_agent_inbox_reply_skipped,
    _record_agent_inbox_wake_event,
    _record_agent_inbox_idle_drain_event,
    _record_agent_inbox_startup_recovery_event,
)
from core.web.services.session.conversation_index import (
    _ensure_conversation_workspace_metadata,
    _conversation_index_kind_from_raw,
    _conversation_index_classification,
    repair_conversation_index_records,
    _legacy_agent_conversation_index_repair_kind,
    _apply_agent_conversation_index_repair_metadata,
    _conversation_repair_flags_match_kind,
    _apply_conversation_index_repair_fields,
    _conversation_index_visibility_for_kind,
    _conversation_index_visibility_for_classification,
    _raw_conversation_session_kind,
    _raw_conversation_root_session_id,
    _conversation_agent_direct_session_is_allowed,
    _repair_conversation_agent_legacy_model_fields,
    _ensure_conversation_agent_metadata,
    _conversation_requires_agent_materialization,
    _sync_agent_directory_project_root,
    _conversation_agent_from_state,
    _get_cached_session_query_sessions,
    query_sessions,
    select_chat_session,
    create_chat_session,
    ensure_agent_direct_session,
    _bind_conversation_to_agent_instance,
    _repair_agent_direct_session_collisions,
    _select_direct_session_collision_owner,
    _agent_direct_session_collision_owner_protected,
    _agent_directory_stub_hidden_from_user_index,
    _agent_directory_stub_hidden_team_member_ids,
    _ensure_agent_directory_conversation_materialized,
    _materialize_agent_directory_conversation_locked,
    _agent_directory_conversation_record,
    _conversation_agent_deleted_tombstone_matches,
    _mark_conversation_agent_deleted,
    _agent_directory_conversation_stub,
    _conversation_agent_dialogue_context_window,
    _conversation_agent_dialogue_context_window_payload,
    _conversation_agent_for_context_limit,
    _find_conversation_entry,
    _new_conversation_id,
    _make_empty_conversation,
    _record_agent_directory_conversation_index_event,
    _record_agent_direct_session_collision_repaired_event,
    _record_agent_directory_conversation_materialized_event,
    _record_session_agent_legacy_model_fields_repaired_event,
)
from core.web.services.session.live_output_write import (
    _session_live_output_checkpoint_path,
    _live_output_checkpoint_payload,
    _write_session_live_output_checkpoint,
    _delete_session_live_output_checkpoint,
    _discard_session_live_output_state,
    _load_session_live_output_checkpoint,
    _persist_recovered_live_output_to_chat_state,
    _build_live_output_message,
    _set_session_live_output,
    _append_session_live_feedback_event,
    _set_session_llm_payload_trace_live_output,
    _set_session_turn_progress_live_output,
    _set_session_llm_status_live_output,
    _set_session_model_thinking_live_output,
)
from core.web.services.session.timeline import (
    _persist_session_preflight_rejection,
    _assistant_timeline_target_indices,
    _finish_image_attachment_preflight_turn,
    _record_session_turn_tool_calls,
    _normalize_tool_call_status,
    _looks_like_tool_call_failure_summary,
    _tool_call_name,
    _normalize_persisted_tool_calls,
    _normalize_message_tool_calls,
    _normalize_feedback_event_kind,
    _normalize_persisted_feedback_events,
    _normalize_message_feedback_events,
    _assistant_timeline_events_by_turn,
    _is_assistant_timeline_segment_event,
    _conversation_tool_timeline_key,
    _feedback_event_from_conversation_tool_event,
    _filter_redundant_assistant_timeline_events,
    _extract_chat_feedback_events,
    _normalize_mental_snapshot,
    _is_mental_model_enabled_for_turn,
    _has_meaningful_mental_snapshot,
    _live_mental_snapshot,
    _build_turn_mental_snapshot,
    _merge_diagnosis_mental_snapshot,
    _record_mental_snapshot_selection,
    _diagnosis_mental_snapshot,
    _mental_diagnosis_summary,
)
from core.web.services.session.turn_diagnostics import (
    _reconcile_stale_session_ledger,
    get_session_turn_completion_snapshot,
    create_chat_review_candidate_from_session,
    _create_direct_session_submit_kernel_trace,
    _record_direct_session_submit_kernel_trace_event,
    _active_chat_turn_work_run_id_for_session,
    _release_stale_chat_turn_work_run,
    _complete_turn_error_visible_content,
    _provider_error_detail_safe_for_chat,
    _normalize_session_references,
    _resolve_session_references,
    _active_chat_turn_work_run_for_session,
    list_active_session_work_runs,
    _active_session_work_run_statuses,
    load_chat_turn_work_run_summary,
    _persist_chat_turn_work_run,
    _reconcile_source_collection_stage_task_after_turn,
    _make_local_runtime_turn_error,
    _record_session_turn_error,
    _record_session_turn_circuit_breaker_event,
    _append_session_workspace_log,
    _normalize_session_turn_error,
    _make_session_turn_error,
    _session_turn_error_to_api,
    _make_turn_error_chat_message,
    _looks_like_provider_error_text,
    _provider_error_user_reason,
    _provider_error_reason_detail,
    _provider_error_diagnostics,
    _iter_provider_error_json,
    _extract_provider_error_type_from_json,
    _sanitize_provider_error_type,
    _extract_provider_error_message_from_json,
    _sanitize_provider_error_detail,
    _user_visible_failure_summary,
    _touch_chat_turn_work_run,
    _record_session_chat_review_candidate_event,
)
from core.web.services.session.agent_runtime import (
    _agent_from_lookup,
    _recover_active_direct_session_agent,
    _session_agent_is_available,
    _release_other_direct_session_agents,
    _normalize_session_agent_llm_bindings,
    default_session_llm_bindings,
    _session_agent_reasoning_effort,
    _session_llm_model_choices,
    _session_agent_id_snapshot,
    get_session_llm_options,
    _normalize_session_agent_profile_id,
    llm_bindings_for_profile_id,
    _session_agent_config_for_llm_bindings,
    _resolve_session_agent_llm,
    _session_agent_config_for_llm_slot,
    _agent_prompt_snapshot_matches_agent,
    _ensure_session_agent_prompt_snapshot,
    _render_agent_prompt_snapshot_block,
    _prompt_snapshot_context_segment,
    _record_session_prompt_snapshot_event,
    _session_agent_supports_image_input,
    _session_agent_dialogue_model_name,
    _session_agent_llm_slot_model_id,
    _session_agent_llm_model_name,
    _image_input_unsupported_message,
    _session_agent_runtime_cache_fingerprint,
    _session_agent_runtime_config_fingerprint_payload,
    _invalidate_session_agent_runtime_cache,
    _acquire_chat_agent_for_session,
    _create_chat_agent_for_session,
    create_chat_agent,
    _attach_session_llm_runtime_diagnostics,
    _session_agent_unavailable_message,
    _record_session_agent_unavailable_event,
    _record_session_llm_usage_event,
    _record_session_agent_binding_recovered_event,
    _record_session_agent_child_direct_binding_repaired_event,
    _record_session_agent_binding_updated_event,
    _record_session_agent_missing_index_event,
    _record_session_agent_missing_index_batch_event,
)
from core.web.services.session.cache_context import (
    _aggregate_session_provider_cache_usage,
    _context_segment_content_preview,
    _attach_context_segment_content_previews,
    _ordered_model_input_context_segments,
    _estimated_provider_prefix_cache_segments,
    _provider_cache_calibration_reason,
    _estimate_context_segment_tokens,
    _context_segment,
    _agent_context_segment_label,
    _session_context_segments_block,
    _session_context_segments_without_prompt_template,
)
from core.web.services.session.image_attachments import (
    store_session_image_artifact,
    store_session_user_image_attachment,
    _remember_session_uploaded_attachment,
    _decode_attachment_filename,
    _session_image_extension_for_upload,
    _sniff_image_extension,
    resolve_session_image_artifact,
    _resolve_session_image_attachment,
    resolve_session_image_attachment_data_url,
    _resolve_session_image_attachments,
    _find_session_attachment_metadata,
    _has_recent_image_attachment_reference,
    _find_recent_user_image_attachment,
    _is_ready_user_image_attachment,
    _normalize_message_attachments,
    _matches_attachment_reference_pattern,
    _contains_any_attachment_reference_pattern,
    _resolve_image_attachment_capability,
    _recent_image_attachment_missing_message,
    _record_image_attachment_capability_event,
    _build_llm_image_attachments,
    _record_session_attachment_event,
    _safe_attachment_log_summary,
)
from core.web.services.session.projection import (
    list_sessions,
    get_session_detail,
    get_active_session_detail,
    get_active_session_summary,
    _build_session_detail,
    _build_session_detail_from_summary,
    _build_session_summary,
    _normalize_conversation,
    _normalize_messages,
    _build_session_active_task,
    _normalize_session_active_task,
    _session_detail_messages_with_window,
    _session_detail_window_requested,
    _build_session_turn_items_projection,
    _build_codex_transcript_projection,
    _build_terminal_error_codex_transcript_projection,
    _codex_tool_lifecycle_projection_from_source,
    _run_session_cycle_message_projection,
    _build_session_cache_usage,
    _build_session_cache_composition,
    _build_session_context_usage,
    _normalize_session_cache_composition,
    _normalize_session_cache_composition_segment,
    _calibrate_session_cache_segments,
    _build_computed_cache_segments,
    _enrich_session_cache_composition,
    _build_last_context_composition,
    _normalize_session_context_composition,
    _normalize_session_llm_payload_trace,
    _normalize_session_runtime_notices,
    _normalize_turn_llm_usage,
    _session_detail_agent_snapshot,
    _active_task_to_api,
    _active_task_with_live_work_run,
    _messages_with_live_output,
    _latest_message_summary,
    _conversation_phase,
    _projection_edit_contract,
    _public_agent_prompt_snapshot,
    _session_agent_status_payload,
    _ledger_visible_messages_for_session,
    _normalize_child_handoff_context,
    _normalize_child_result_card,
    _load_conversations,
    _append_agent_directory_conversations,
    _agent_lookup_for_conversations,
    _empty_direct_agent_session_hidden_from_index,
    _session_agent_visible_in_indexes,
    _with_direct_session_agent_for_summary,
    _timestamp_sort_key,
    _is_default_empty_session_title,
    _agent_inbox_pending_count_for_summary,
)
from core.web.services.session.publish import (
    stream_session_events,
    get_session_stream_initial_state,
    resolve_session_stream_initial_payload,
    normalize_session_stream_initial_mode,
    _session_stream_initial_latest_message_payload,
    _latest_session_stream_preview_message,
    _session_stream_preview_message_components,
    _publish_session_detail_snapshot,
    _publish_session_assistant_delta,
    _merge_session_assistant_delta_events,
    _coalesce_session_assistant_delta_queue,
    _session_assistant_delta_feedback_event_key,
    _merge_session_assistant_delta_feedback_events,
    _put_session_stream_event,
    _drop_session_stream_event_for_room,
    _assistant_delta_recovery_stream_event,
    _coalesce_session_stream_queue,
    _register_session_stream_subscriber,
    _unregister_session_stream_subscriber,
    _encode_sse_event,
    _record_session_assistant_delta_published_event,
    _record_session_detail_snapshot_published_event,
    _record_session_detail_snapshot_throttled_event,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CHAT_STATE_LOCK = threading.RLock()


def session_agent_lifecycle_serialized(
    callback: Callable[..., Any],
) -> Callable[..., Any]:
    """Serialize chat state before entering the shared Agent lifecycle lock."""

    @wraps(callback)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with session_agent_lifecycle_transaction():
            return callback(*args, **kwargs)

    return wrapped


@contextmanager
def session_agent_lifecycle_transaction():
    """Hold chat state before the shared Agent lifecycle serialization lock."""

    with (
        _CHAT_STATE_LOCK,
        agent_directory_service.agent_session_lifecycle_transaction(),
    ):
        yield


# Re-apply lifecycle serialization after decorator definition (packs export bare bodies).
archive_agent_sessions = session_agent_lifecycle_serialized(archive_agent_sessions)
stage_agent_session_purge = session_agent_lifecycle_serialized(stage_agent_session_purge)
restore_staged_agent_session_purge = session_agent_lifecycle_serialized(restore_staged_agent_session_purge)
retry_pending_agent_session_purge_cleanup = session_agent_lifecycle_serialized(
    retry_pending_agent_session_purge_cleanup
)
commit_staged_agent_session_purge = session_agent_lifecycle_serialized(commit_staged_agent_session_purge)


_RUNNING_SESSIONS_LOCK = threading.Lock()
_RUNNING_SESSION_IDS: set[str] = set()
_SESSION_ACTIVE_TURN_IDS: dict[str, str] = {}
_SESSION_ACTIVE_TURN_LEASES: dict[str, list[str]] = {}
_AGENT_INBOX_WAKE_STATE_LOCK = threading.Lock()
_AGENT_INBOX_IDLE_DRAINING_SESSION_IDS: set[str] = set()
_AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS: set[str] = set()
_SESSION_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-chat-turn")
_SESSION_CYCLE_PROJECTION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="web-chat-cycle-projection",
)
_SESSION_AGENT_MAX_ACTIVE_TURNS = 4
SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND = "source_collection_stage_session_task"
INTERNAL_AUTO_CONTINUE_MAX_TURNS = 3
SOURCE_COLLECTION_STAGE_TASK_AUTO_CONTINUE_MAX_TURNS = 4
_SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_SESSION_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_SESSION_STREAM_HEARTBEAT_SECONDS = 15.0
_SESSION_STREAM_QUEUE_SIZE = 8
_SESSION_STREAM_COALESCED_EVENT_TYPES = {"session_detail"}
_SESSION_STREAM_BUSY_PHASES = {"queued", "running", "stopping", "paused"}
_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS = 0.75
_SESSION_STREAM_DETAIL_MESSAGE_LIMIT = 40
_SESSION_STREAM_DETAIL_TRANSCRIPT_SCOPE = "window"
_SESSION_STREAM_LAST_SNAPSHOT_LOCK = threading.Lock()
_SESSION_STREAM_LAST_SNAPSHOT_AT: dict[str, float] = {}
_SESSION_STREAM_THROTTLED_COUNTS: dict[str, int] = {}
_SESSION_TURN_CONTROLS_LOCK = threading.Lock()
_SESSION_TURN_CONTROLS: dict[str, "SessionTurnControl"] = {}
_SESSION_AGENT_RUNTIME_CACHE_LOCK = threading.Lock()
_SESSION_AGENT_RUNTIME_CACHE_MAX_ENTRIES = 16
_SESSION_AGENT_RUNTIME_CACHE: dict[str, dict[str, Any]] = {}
_SESSION_AGENT_RUNTIME_CONFIG_FINGERPRINT_KEYS = (
    "llm",
    "agent",
    "context_compression",
)
_SESSION_DETAIL_MESSAGE_WINDOW_MAX_LIMIT = 200
_AGENT_DIRECTORY_STUB_HIDDEN_TEAM_SOURCES = {
    "ai_search",
    "research_organization",
    "self_evolution",
    "supervised_evolution",
}
_AGENT_DIRECTORY_STUB_HIDDEN_TEAM_KINDS = {
    "ai_search",
    "research",
    "self_evolution",
    "supervised_evolution",
}
_SESSION_LIST_PREWARM_LOCK = threading.Lock()
_SESSION_LIST_PREWARM_INFLIGHT = False
_UNSET = object()
_WORK_RUN_STORE = WorkRunStore()
_NO_VISIBLE_REPLY_ZH = "本轮没有产生可见回复。"
_NO_VISIBLE_REPLY_EN = "This turn did not produce a visible reply."
_PROVIDER_ERROR_PATTERN = re.compile(
    r"(?:provider_protocol_error|server_error|litellm\.|badgatewayerror|openai(?:exception|error)|"
    r"upstream_error|upstream request failed|api(?:connection|status|timeout|rate)?error)",
    re.IGNORECASE,
)
_REPLACEMENT_ONLY_PREFIX_PATTERN = re.compile(r"^\?{3,}(?=[:：\s]|$)")
_REPLACEMENT_ONLY_TEXT_PATTERN = re.compile(r"^\?{3,}$")
_SESSION_WORKSPACE_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_SESSION_IMAGE_ARTIFACT_SAFE_CHARS = re.compile(r"^[A-Za-z0-9_.-]+$")
_SESSION_WORKSPACE_SUBDIRS = ("artifacts", "tmp", "mental_model", "notes", "logs", "memory")
_SESSION_INDEX_EVENT_DEDUPE_LOCK = threading.Lock()
_SESSION_MISSING_INDEX_EVENT_KEYS: set[tuple[str, str, str, str, str]] = set()
_SESSION_MISSING_INDEX_BATCH_EVENT_KEYS: set[tuple[Any, ...]] = set()
_AGENT_DIRECTORY_INDEX_EVENT_KEYS: set[tuple[str, str, str]] = set()
_DIRECT_SESSION_COLLISION_REPAIR_LOCK = threading.Lock()
_DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE: tuple[Any, ...] | None = None
_SESSION_IMAGE_ARTIFACT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
_SESSION_USER_IMAGE_MAX_BYTES = 8 * 1024 * 1024
SESSION_USER_IMAGE_MAX_BYTES = _SESSION_USER_IMAGE_MAX_BYTES
SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC = "chat_agent_static"
SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK = "chat_session_fallback"


def _perf_counter() -> float:
    return time.perf_counter()


def _invalidate_session_list_cache() -> None:
    """Clear list cache and any direct-session collision repair fingerprint."""

    global _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE
    _invalidate_session_list_cache_core()
    with _DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = None


def _session_conversation_events_signature(session_id: str) -> tuple[str, int, int, int]:
    return _journal_bridge.session_conversation_events_signature(
        session_id,
        project_root=PROJECT_ROOT,
    )


def _invalidate_session_conversation_events_cache(session_id: str = "") -> None:
    _journal_bridge.invalidate_session_conversation_events_cache(session_id)


def _load_session_conversation_events_cached(session_id: str) -> list[Any]:
    return _journal_bridge.load_session_conversation_events_cached(
        session_id,
        project_root=PROJECT_ROOT,
    )


def load_session_conversation_events_snapshot(session_id: str) -> list[Any]:
    """Return the current session ledger snapshot through the shared signature cache."""

    return _journal_bridge.load_session_conversation_events_snapshot(
        session_id,
        project_root=PROJECT_ROOT,
    )


def _session_ledger_sequence(session_id: str) -> int:
    return _journal_bridge.session_ledger_sequence(session_id, project_root=PROJECT_ROOT)


def _append_session_conversation_event(
    session_id: str,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "session_service",
    visible_in_model: bool = True,
    projection_kind: str = "",
    tool_call_id: str = "",
    correlation_id: str = "",
    source_kind: str = "",
) -> None:
    _journal_bridge.append_session_conversation_event(
        session_id,
        turn_id,
        event_type,
        status=status,
        payload=payload,
        source=source,
        visible_in_model=visible_in_model,
        projection_kind=projection_kind,
        tool_call_id=tool_call_id,
        correlation_id=correlation_id,
        source_kind=source_kind,
        project_root=PROJECT_ROOT,
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def _elapsed_ms_between(started_at: Any, ended_at: float | None = None) -> int:
    try:
        start_value = float(started_at)
    except (TypeError, ValueError):
        return 0
    end_value = _perf_counter() if ended_at is None else float(ended_at)
    return max(0, int(round((end_value - start_value) * 1000)))
_RECENT_IMAGE_REFERENCE_EXACT_PATTERNS = (
    "这张图",
    "这张图片",
    "这个图片",
    "这个图",
    "那张图",
    "那张图片",
    "刚才那张图",
    "刚才的图",
    "刚才的图片",
    "刚刚那张图",
    "上一张图",
    "上一张图片",
    "上张图",
    "前面那张图",
    "之前那张图",
    "之前的图片",
    "我发的图",
    "我发的图片",
    "发的截图",
    "发的照片",
    "the image",
    "that image",
    "this image",
    "previous image",
    "last image",
    "uploaded image",
    "the picture",
    "that picture",
    "previous picture",
    "last picture",
    "the screenshot",
    "that screenshot",
)
_RECENT_IMAGE_REFERENCE_WORDS = (
    "刚才",
    "刚刚",
    "上一",
    "上张",
    "前面",
    "之前",
    "刚发",
    "我发",
    "发过",
    "这张",
    "这个",
    "那张",
    "那个",
    "previous",
    "last",
    "uploaded",
    "this",
    "that",
)
_RECENT_IMAGE_TARGET_WORDS = (
    "图",
    "图片",
    "照片",
    "截图",
    "画面",
    "image",
    "picture",
    "photo",
    "screenshot",
)
_SESSION_USER_IMAGE_MAX_ATTACHMENTS_PER_TURN = 4
DEFAULT_SESSION_AGENT_PROFILE_ID = "primary"
SESSION_LLM_SLOT_DIALOGUE = "dialogue"
SESSION_LLM_SLOT_VISION = "vision"


class SessionNotFoundError(ValueError):
    """Raised when a requested session id does not exist."""


class SessionBusyError(RuntimeError):
    """Raised when a session already has an active running turn."""


class SessionValidationError(ValueError):
    """Raised when an incoming session turn payload is invalid."""


class SessionChatReviewCandidateExistsError(RuntimeError):
    """Raised when the session snapshot is already queued for chat review."""


def _short_hash(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _session_workspace_relative_path(session_id: str) -> str:
    return f"workspace/sessions/{_safe_session_workspace_token(session_id)}"


def _ensure_session_workspace(session_id: str) -> Path:
    token = _safe_session_workspace_token(session_id)
    sessions_root = developer_sandbox.sandboxed_workspace_path(PROJECT_ROOT, "sessions").resolve()
    workspace_path = (sessions_root / token).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise SessionValidationError(f"Invalid session workspace path: {workspace_path}")
    formal_workspace_path = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "sessions", token)
    if not workspace_path.exists() and formal_workspace_path.exists():
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(formal_workspace_path, workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)
    for subdir in _SESSION_WORKSPACE_SUBDIRS:
        (workspace_path / subdir).mkdir(parents=True, exist_ok=True)
    return workspace_path


def _image_context_request_for_retry(
    message: str,
    *,
    conversation: dict[str, Any] | None,
) -> dict[str, Any]:
    if not (_is_continue_request(message) or _is_contextual_confirmation_message(message)):
        return {}
    if not isinstance(conversation, dict):
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for item in reversed(_session_ledger_visible_messages(conversation_id)[-8:]):
        if not isinstance(item, dict) or str(item.get("role") or "").strip().lower() != "user":
            continue
        request = _image_context_request_from_user_message(item)
        if request:
            return request
    return {}


def _image_context_request_from_user_message(message: dict[str, Any]) -> dict[str, Any]:
    attachments = _normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
    artifact_ids = [
        str(item.get("artifactId") or "").strip()
        for item in attachments
        if _is_ready_user_image_attachment(item) and str(item.get("artifactId") or "").strip()
    ]
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    resolved_reference = (
        metadata.get("resolvedRecentImageReference")
        if isinstance(metadata.get("resolvedRecentImageReference"), dict)
        else {}
    )
    resolved_artifact_ids = [
        str(item or "").strip()
        for item in list(resolved_reference.get("artifactIds") or [])
        if str(item or "").strip()
    ]
    if resolved_artifact_ids:
        artifact_ids = resolved_artifact_ids
    if not artifact_ids:
        return {}

    prompt = trim_lines(message.get("content") or "", max_lines=4)
    if prompt and _is_retriable_image_request_prompt(prompt):
        return {"prompt": prompt, "artifactIds": artifact_ids}
    return {}


def _is_retriable_image_request_prompt(prompt: Any) -> bool:
    return _looks_like_image_retry_context(prompt)


def _image_context_prompt_for_retry(
    message: str,
    *,
    conversation: dict[str, Any] | None,
    active_task: dict[str, Any] | None = None,
) -> str:
    request = _image_context_request_for_retry(message, conversation=conversation)
    return str(request.get("prompt") or "")


def _looks_like_image_retry_context(text: Any) -> bool:
    value = str(text or "").strip().lower()
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return False
    image_terms = ("原图", "原来的图片", "原来的图", "图片", "图像", "画面", "图", "image", "picture")
    retry_terms = (
        "再看",
        "重新看",
        "逼近",
        "调整提示词",
        "继续调整",
        "重绘",
        "生成的图片",
        "完全不一样",
        "参考",
        "match",
        "reference",
        "retry",
    )
    return any(term in compact for term in image_terms) and any(term in compact for term in retry_terms)


def append_session_assistant_artifact_message(
    session_id: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    tool_calls: list[Any] | None = None,
) -> dict[str, Any]:
    """Append an assistant artifact message and notify session subscribers."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionValidationError("Session id is required for artifact messages.")
    status = str((metadata or {}).get("status") or "observed").strip() or "observed"
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        assistant_entry = _make_chat_message(
            "assistant",
            content,
            tool_calls or [],
            metadata=metadata,
        )
        conversation.pop("messages", None)
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
    turn_id = str((metadata or {}).get("turnId") or (metadata or {}).get("turn_id") or f"artifact:{assistant_entry['timestamp']}").strip()
    _append_session_conversation_event(
        normalized_session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status=status,
        payload={
            "content": content,
            "toolCalls": _normalize_message_tool_calls(tool_calls or []),
            "metadata": metadata or {},
        },
        source="append_session_assistant_artifact_message",
    )

    _record_session_cycle_message(
        normalized_session_id,
        assistant_entry,
        event="assistant_artifact",
        status=status,
    )
    _publish_session_detail_snapshot(normalized_session_id)
    normalized = _normalize_messages(normalized_session_id, [assistant_entry])
    return normalized[0] if normalized else assistant_entry


def _agent_created_by(agent: dict[str, Any], metadata: dict[str, Any]) -> str:
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    return str(agent.get("createdBy") or creation_spec.get("source") or "").strip()


def _agent_needs_ai_search_team_marker(agent: dict[str, Any], metadata: dict[str, Any]) -> bool:
    role_key = str(agent.get("roleKey") or metadata.get("aiSearchRole") or "").strip()
    return (
        _agent_created_by(agent, metadata) == "ai_search_team"
        or bool(str(metadata.get("aiSearchRole") or "").strip())
        or role_key.startswith("ai_search_")
    )


def _ai_search_team_id_for_repair() -> str:
    try:
        from . import team_service

        return str(team_service.AI_SEARCH_TEAM_ID or "").strip() or "ai-search-team"
    except Exception:
        return "ai-search-team"


def _conversation_hidden_from_index(
    raw: dict[str, Any],
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> bool:
    classification = _conversation_index_classification(
        raw,
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    kind = str(classification.get("kind") or "").strip()
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        return False
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return True
    return bool(raw.get("hidden_from_index") or raw.get("hiddenFromIndex"))


def _repair_child_root_agent_direct_session_bindings(
    payload: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> bool:
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return False
    changed = False
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(conversation.get("conversation_id") or "").strip()
        if not conversation_id or _raw_conversation_session_kind(conversation) == "child":
            continue
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        if not agent_id:
            continue
        agent = _agent_from_lookup(agent_by_id, agent_id)
        if not agent:
            continue
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if not direct_session_id or direct_session_id not in _raw_conversation_child_session_ids(conversation):
            continue
        title = str(conversation.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip() or DEFAULT_CHAT_CONVERSATION_TITLE
        session_workspace = str(conversation.get("workspace_path") or _session_workspace_relative_path(conversation_id))
        repaired_agent = ensure_agent_for_session(
            conversation_id,
            display_name=title,
            llm_bindings=agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings")),
            primary_mode=str(agent.get("primaryMode") or agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE).strip()
            or agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE,
            role_key=str(agent.get("roleKey") or "").strip(),
            prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
            existing_agent_id=agent_id,
            session_workspace_path=session_workspace,
        )
        agent_by_id[agent_id] = _conversation_agent_from_state(repaired_agent)
        _record_session_agent_child_direct_binding_repaired_event(
            conversation_id,
            agent_id=agent_id,
            previous_direct_session_id=direct_session_id,
        )
        changed = True
    return changed


def _agent_team_identity(agent: dict[str, Any], metadata: dict[str, Any]) -> dict[str, str]:
    generic_team_id = str(metadata.get("teamId") or "").strip()
    generic_team_name = str(metadata.get("teamName") or "").strip()
    if generic_team_id:
        return {"teamId": generic_team_id, "teamName": generic_team_name}

    challenge_team_id = str(metadata.get("challengeCupTeamId") or "").strip()
    challenge_team_name = str(metadata.get("challengeCupTeamName") or "").strip()
    knowledge_team_id = str(metadata.get("knowledgeExpansionTeamId") or "").strip()
    knowledge_team_name = str(metadata.get("knowledgeExpansionTeamName") or "").strip()
    role_text = " ".join(
        str(value or "").strip()
        for value in (
            agent.get("roleKey"),
            metadata.get("researchTeamRole"),
            metadata.get("researchTeamRoleKey"),
            metadata.get("challengeCupTeamRole"),
            metadata.get("challengeCupTeamRoleKey"),
            metadata.get("knowledgeExpansionTeamRole"),
            metadata.get("knowledgeExpansionTeamRoleKey"),
        )
        if str(value or "").strip()
    ).lower()

    if knowledge_team_id and ("knowledge" in role_text or not challenge_team_id):
        return {"teamId": knowledge_team_id, "teamName": knowledge_team_name}
    if challenge_team_id:
        return {"teamId": challenge_team_id, "teamName": challenge_team_name}
    if knowledge_team_id:
        return {"teamId": knowledge_team_id, "teamName": knowledge_team_name}
    return {"teamId": "", "teamName": ""}


def _agent_avatar_path(agent: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    source = metadata if isinstance(metadata, dict) else agent.get("metadata")
    meta = source if isinstance(source, dict) else {}
    raw_path = str(meta.get("avatarImagePath") or "").strip()
    filename = agent_directory_service.agent_avatar_filename(raw_path)
    if not filename:
        return ""
    return str(agent_directory_service.AGENT_AVATAR_RELATIVE_DIR / filename)


def _archived_agent_for_direct_session(session_id: str) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        agents = agent_directory_service.list_agents(include_archived=True)
    except Exception:
        return None
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            return agent
    return None


def _resolve_active_agent_for_turn(
    session_id: str,
    agent_id: str,
    *,
    lang: str,
) -> dict[str, Any]:
    normalized_agent_id = str(agent_id or "").strip()
    active_agent = get_agent(normalized_agent_id, include_archived=False) if normalized_agent_id else None
    if active_agent:
        return active_agent
    historical_agent = get_agent(normalized_agent_id, include_archived=True) if normalized_agent_id else None
    status = str((historical_agent or {}).get("status") or "").strip().lower()
    reason = "archived_agent" if status == "archived" else "missing_agent"
    _record_session_agent_unavailable_event(
        session_id,
        agent_id=normalized_agent_id,
        reason=reason,
        agent_status=status,
    )
    raise SessionValidationError(_session_agent_unavailable_message(reason, lang=lang))


@contextmanager
def _session_tool_workspace_override(
    session_workspace: str | Path,
    memory_workspace: str | Path | None = None,
    task_workspace: str | Path | None = None,
):
    try:
        from core.infrastructure.mental_model import active_mental_workspace
        from core.orchestration.task_planner import task_storage_override
        from tools.shell_tools import workspace_root_override
        from tools.memory_tools import memory_storage_override
    except Exception:
        yield
        return
    memory_root = memory_workspace or session_workspace
    task_root = task_workspace or session_workspace
    with (
        active_mental_workspace(session_workspace),
        workspace_root_override(session_workspace),
        memory_storage_override(memory_root),
        task_storage_override(task_root),
    ):
        yield


@dataclass
class SessionTurnControl:
    """Ephemeral runtime control surface for one active web chat turn."""

    session_id: str
    turn_id: str = ""
    stop_requested: bool = False
    stop_requested_at: str = ""
    stop_reason: str = ""
    released_to_user: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def request_stop(self, reason: str) -> None:
        with self._lock:
            if self.stop_requested:
                if reason and not self.stop_reason:
                    self.stop_reason = str(reason).strip()
                return
            self.stop_requested = True
            self.stop_requested_at = _now_timestamp()
            self.stop_reason = str(reason or "").strip()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "turnId": self.turn_id,
                "stopRequested": self.stop_requested,
                "stopRequestedAt": self.stop_requested_at,
                "stopReason": self.stop_reason,
                "releasedToUser": self.released_to_user,
            }

    def mark_released_to_user(self) -> None:
        with self._lock:
            self.released_to_user = True



def prewarm_session_list_cache(*, reason: str = "startup") -> dict[str, Any]:
    """Build the lightweight session list cache before the first user query."""

    global _SESSION_LIST_PREWARM_INFLIGHT
    normalized_reason = trim_lines(reason, max_lines=1) or "startup"
    started_at = _perf_counter()
    with _SESSION_LIST_PREWARM_LOCK:
        if _SESSION_LIST_PREWARM_INFLIGHT:
            return {
                "status": "skipped",
                "reason": normalized_reason,
                "skipReason": "inflight",
                "durationMs": _elapsed_ms(started_at),
            }
        _SESSION_LIST_PREWARM_INFLIGHT = True

    try:
        sessions = list_sessions()
        duration_ms = _elapsed_ms(started_at)
        result = {
            "status": "completed",
            "reason": normalized_reason,
            "sessionCount": len(sessions),
            "durationMs": duration_ms,
        }
        _record_session_list_prewarm_event(
            status="completed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            session_count=len(sessions),
        )
        return result
    except Exception as exc:
        duration_ms = _elapsed_ms(started_at)
        _record_session_list_prewarm_event(
            status="failed",
            reason=normalized_reason,
            elapsed_ms=duration_ms,
            error_type=type(exc).__name__,
            error_message=trim_lines(str(exc), max_lines=2),
        )
        return {
            "status": "failed",
            "reason": normalized_reason,
            "durationMs": duration_ms,
            "errorType": type(exc).__name__,
        }
    finally:
        with _SESSION_LIST_PREWARM_LOCK:
            _SESSION_LIST_PREWARM_INFLIGHT = False


_SESSION_QUERY_MAX_LIMIT = 100
_SESSION_QUERY_DEFAULT_LIMIT = 50


def _coerce_session_query_limit(value: Any) -> int:
    limit = _coerce_nonnegative_int(value)
    if limit <= 0:
        return _SESSION_QUERY_DEFAULT_LIMIT
    return min(limit, _SESSION_QUERY_MAX_LIMIT)


def _coerce_session_detail_message_limit(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    limit = _coerce_nonnegative_int(value)
    if limit <= 0:
        return None
    return min(limit, _SESSION_DETAIL_MESSAGE_WINDOW_MAX_LIMIT)


def _coerce_session_detail_before_index(value: Any) -> int:
    return max(0, _coerce_nonnegative_int(value))


def _normalize_session_detail_transcript_scope(value: Any) -> str:
    normalized = str(value or "all").strip().lower()
    return normalized if normalized in {"all", "window", "none"} else "all"


def _normalize_session_query_sort(value: str) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"updatedAt_desc", "updatedAt_asc", "title_asc", "title_desc"} else "updatedAt_desc"


def _session_query_sort_key(sort: str):
    if sort.startswith("title"):
        return lambda item: str(item.get("title") or "").strip().lower()
    return lambda item: _timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or "")


def _session_query_matches(
    item: dict[str, Any],
    *,
    query: str,
    agent_id: str,
    session_kind: str,
    state: str,
) -> bool:
    if agent_id and str(item.get("agentId") or "").strip() != agent_id:
        return False
    if session_kind and str(item.get("sessionKind") or "").strip().lower() != session_kind:
        return False
    if state:
        values = {
            str(item.get("status") or "").strip().lower(),
            str(item.get("currentPhase") or "").strip().lower(),
            str(item.get("childStatus") or "").strip().lower(),
        }
        if state not in values:
            return False
    if not query:
        return True
    haystack = " ".join(
        str(item.get(key) or "")
        for key in (
            "id",
            "title",
            "taskTitle",
            "taskSummary",
            "agentId",
            "agentCode",
            "agentDisplayName",
            "dialogueModelId",
            "sessionKind",
            "status",
            "currentPhase",
        )
    ).lower()
    return query in haystack


def _current_session_turn_id(session_id: str) -> str:
    with _RUNNING_SESSIONS_LOCK:
        return str(_SESSION_ACTIVE_TURN_IDS.get(session_id) or "").strip()


def _load_active_conversation_summary_target(
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Normalize only the persisted active conversation for polling fast paths."""

    with _CHAT_STATE_LOCK, chat_state_transaction(PROJECT_ROOT):
        payload = load_chat_state(PROJECT_ROOT)
        active_id = str(payload.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
        raw_target = _find_conversation_entry(payload, active_id)
        if raw_target is None:
            return active_id, None
        target = _normalize_conversation(
            raw_target,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=_agent_directory_stub_hidden_team_member_ids(),
            ensure_workspace=False,
            lightweight=True,
        )
        return active_id, target


def update_chat_session(
    session_id: str,
    *,
    title: str | None = None,
    agent_id: str | None = None,
) -> dict:
    """Persist user-facing chat session settings."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    normalized_title: str | None = None
    if title is not None:
        normalized_title = trim_lines(title or "", max_lines=1).strip()
        if not normalized_title:
            raise SessionValidationError(text_for(lang, zh="请输入会话名称。", en="Enter a session name."))
        if len(normalized_title) > 120:
            normalized_title = normalized_title[:120].rstrip()

    normalized_agent_id: str | None = None
    selected_agent: dict[str, Any] | None = None
    if agent_id is not None:
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id:
            raise SessionValidationError(text_for(lang, zh="请选择会话 Agent。", en="Choose a session Agent."))
        selected_agent = get_agent(normalized_agent_id, include_archived=False)
        if not selected_agent:
            raise SessionValidationError(text_for(lang, zh=f"未找到会话 Agent：{normalized_agent_id}", en=f"Session Agent not found: {normalized_agent_id}"))

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_session_mutable(conversation_id, conversation=conversation)
        changed = False
        changed = _ensure_conversation_workspace_metadata(conversation) or changed
        changed = _ensure_conversation_agent_metadata(conversation) or changed

        if normalized_title is not None and conversation.get("title") != normalized_title:
            conversation["title"] = normalized_title
            changed = True
        if selected_agent is not None and normalized_agent_id is not None:
            _bind_conversation_to_agent_instance(
                conversation,
                selected_agent,
                session_id=conversation_id,
                source="agent_id",
            )
            changed = True
        changed = _ensure_conversation_agent_metadata(conversation) or changed
        if changed:
            payload["updated_at"] = _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)

    if changed:
        _invalidate_session_list_cache()
        _publish_session_detail_snapshot(conversation_id)
    return get_session_detail(conversation_id) or {}


def update_chat_session_title(session_id: str, title: str) -> dict:
    """Persist a user-facing chat session title."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    normalized_title = trim_lines(title or "", max_lines=1).strip()
    if not normalized_title:
        raise SessionValidationError(text_for(lang, zh="请输入会话名称。", en="Enter a session name."))
    if len(normalized_title) > 120:
        normalized_title = normalized_title[:120].rstrip()

    changed = False
    agent_id_to_refresh = ""
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_session_mutable(conversation_id, conversation=conversation)

        session_kind = str(conversation.get("session_kind") or conversation.get("sessionKind") or "main").strip().lower()
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        if session_kind == "child":
            if str(conversation.get("task_title") or conversation.get("taskTitle") or "").strip() != normalized_title:
                conversation["task_title"] = normalized_title
                conversation["taskTitle"] = normalized_title
                conversation["title"] = normalized_title
                conversation["updated_at"] = _now_timestamp()
                payload["updated_at"] = str(conversation.get("updated_at") or _now_timestamp())
                save_chat_state(PROJECT_ROOT, payload)
                changed = True
        elif agent_id:
            agent_id_to_refresh = agent_id
            if str(conversation.get("title") or "").strip() != normalized_title:
                conversation["title"] = normalized_title
                conversation["updated_at"] = _now_timestamp()
                payload["updated_at"] = str(conversation.get("updated_at") or _now_timestamp())
                save_chat_state(PROJECT_ROOT, payload)
                changed = True
        elif str(conversation.get("title") or "").strip() != normalized_title:
            conversation["title"] = normalized_title
            conversation["updated_at"] = _now_timestamp()
            payload["updated_at"] = str(conversation.get("updated_at") or _now_timestamp())
            save_chat_state(PROJECT_ROOT, payload)
            changed = True

    agent_by_id: dict[str, dict[str, Any]] = {}
    if agent_id_to_refresh:
        updated_agent = update_agent_instance(agent_id_to_refresh, display_name=normalized_title)
        agent_by_id[agent_id_to_refresh] = updated_agent
        changed = True

    target = _load_conversation_detail_target(
        conversation_id,
        repair=False,
        agent_by_id=agent_by_id if agent_by_id else None,
    )
    detail = _build_lightweight_session_detail(target) if target is not None else {}
    if changed:
        _invalidate_session_list_cache()
        if detail:
            _publish_session_detail_snapshot(conversation_id, detail=detail)
        else:
            _publish_session_detail_snapshot(conversation_id)
    return detail


def _remove_replacement_direct_session_after_failed_agent_reset(
    session_id: str,
    *,
    agent_id: str,
    fallback_active_session_id: str,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            return
        remaining = []
        changed = False
        for item in conversations:
            if not isinstance(item, dict):
                continue
            if str(item.get("conversation_id") or "").strip() == normalized_session_id:
                changed = True
                continue
            remaining.append(item)
        if not changed:
            return
        fallback_id = str(fallback_active_session_id or "").strip()
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in remaining
            if isinstance(item, dict)
        }
        if fallback_id and fallback_id in existing_ids:
            payload["active_conversation_id"] = fallback_id
        elif payload.get("active_conversation_id") == normalized_session_id:
            payload["active_conversation_id"] = next(iter(existing_ids), "")
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["updated_at"] = _now_timestamp()
        payload["conversations"] = remaining
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    _record_session_delete_event(
        "agent_reset_replacement_rolled_back",
        session_id=normalized_session_id,
        outcome="rolled_back",
        fields={"agentId": str(agent_id or "").strip(), "fallbackActiveSessionId": str(fallback_active_session_id or "").strip()},
    )


def _supersede_active_session_turn_for_edit(session_id: str, *, lang: str) -> str:
    controller = _get_session_turn_control(session_id)
    if controller is None:
        controller = _restore_missing_session_turn_control(session_id)
    turn_id = str(getattr(controller, "turn_id", "") or "").strip()
    if not turn_id:
        return ""
    reason = text_for(
        lang,
        zh="用户编辑并重新提交了最新消息，当前轮已被新输入取代。",
        en="The user edited and resubmitted the latest message, superseding the active turn.",
    )
    controller.request_stop(reason)
    _cancel_queued_session_turn(session_id, turn_id)
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="superseded",
        summary=reason,
        finished_at=_now_timestamp(),
        updated_at=_now_timestamp(),
    )
    _set_session_running(session_id, False, turn_id=turn_id)
    _clear_session_turn_control(session_id, turn_id=turn_id)
    _clear_session_live_output(session_id, turn_id=turn_id)
    _record_chat_next_state_signal(
        session_id=session_id,
        turn_id=turn_id,
        source="user",
        kind="user_edit_supersedes_turn",
        polarity="neutral",
        mode="directive",
        related_event_code="conversation.message_edited_resubmitted",
        summary=reason,
        metadata={"supersededTurnId": turn_id},
    )
    _record_session_turn_lifecycle_event(
        session_id,
        "superseded_by_edit_resubmit",
        turn_id=turn_id,
        outcome="superseded",
        fields={
            "reason": "edit_resubmit",
        },
    )
    return turn_id



def _restore_missing_session_turn_control(session_id: str) -> SessionTurnControl:
    """Recreate a lost stop controller without changing the active run identity."""

    active_turn_id = _active_chat_turn_id_for_session(session_id)
    if active_turn_id:
        _record_missing_session_turn_control_recovery(session_id, active_turn_id, reused_active_run=True)
        return _create_session_turn_control(session_id, turn_id=active_turn_id)
    _record_missing_session_turn_control_recovery(session_id, "", reused_active_run=False)
    return _create_session_turn_control(session_id)


def _active_chat_turn_id_for_session(session_id: str) -> str:
    active = _WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return ""
    if str(active.get("sessionId") or "").strip() != str(session_id or "").strip():
        return ""
    status = str(active.get("status") or active.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return ""
    return str(active.get("runId") or "").strip()


def _record_missing_session_turn_control_recovery(
    session_id: str,
    turn_id: str,
    *,
    reused_active_run: bool,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_control_recovery",
            "conversation.turn_control_recovered",
            level="warning",
            outcome="reused_active_run" if reused_active_run else "created_new_turn",
            message="Recovered a missing web chat turn controller.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "reusedActiveRun": bool(reused_active_run),
            },
            lifecycle=True,
        )
    except Exception:
        return







def _validate_user_message_not_encoding_replacement(message: str, *, lang: str) -> None:
    if not _looks_like_encoding_replacement_message(message):
        return
    _record_session_message_encoding_rejected(message)
    raise SessionValidationError(
        text_for(
            lang,
            zh="消息看起来已在进入后端前发生编码损坏，请刷新页面后重新输入原始中文。",
            en="The message appears to have been corrupted before it reached the backend. Refresh the page and re-enter the original text.",
        )
    )


def _looks_like_encoding_replacement_message(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    if _REPLACEMENT_ONLY_TEXT_PATTERN.fullmatch(text):
        return True
    if _REPLACEMENT_ONLY_PREFIX_PATTERN.match(text):
        return True
    question_count = text.count("?")
    if question_count < 3:
        return False
    non_space_count = sum(1 for char in text if not char.isspace())
    return non_space_count > 0 and question_count / non_space_count >= 0.8


def _record_session_message_encoding_rejected(message: str) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "message_validation",
            "conversation.message_encoding_rejected",
            level="warning",
            outcome="rejected",
            message="Rejected a user message that appears to contain replacement characters from upstream encoding loss.",
            fields={
                "length": len(str(message or "")),
                "questionMarkCount": str(message or "").count("?"),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _load_conversation_detail_target(
    session_id: str,
    *,
    payload: dict[str, Any] | None = None,
    repair: bool = True,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    lightweight: bool = False,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    payload = payload if isinstance(payload, dict) else load_chat_state(PROJECT_ROOT)
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    agent_by_id = agent_by_id if agent_by_id is not None else _agent_lookup_for_conversations()
    hidden_team_member_agent_ids = _agent_directory_stub_hidden_team_member_ids()
    changed = False
    if repair:
        changed = _repair_child_root_agent_direct_session_bindings(payload, agent_by_id=agent_by_id) or changed
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        raw_session_id = str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
        if raw_session_id != normalized_session_id:
            continue
        if repair:
            changed = _repair_stale_running_conversation(raw) or changed
            changed = _ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
            changed = _ensure_conversation_workspace_metadata(raw) or changed
        conversation = _normalize_conversation(
            raw,
            agent_by_id=agent_by_id,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            ensure_workspace=repair,
            lightweight=lightweight,
        )
        if changed:
            payload["updated_at"] = _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)
        return conversation
    return None


def _agent_direct_session_collision_owner_sort_key(agent: dict[str, Any]) -> tuple[int, str, str]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    previous_direct_session_id = str(metadata.get("previousDirectSessionId") or "").strip()
    return (
        1 if previous_direct_session_id else 0,
        str(agent.get("updatedAt") or agent.get("createdAt") or ""),
        str(agent.get("agentId") or ""),
    )


def _agent_direct_session_collision_repair_sort_key(agent: dict[str, Any]) -> tuple[str, str]:
    return (
        str(agent.get("updatedAt") or agent.get("createdAt") or ""),
        str(agent.get("agentId") or ""),
    )


def _agent_directory_session_stub_for_id(
    session_id: str,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    agents = list((agent_by_id if agent_by_id is not None else _agent_lookup_for_conversations()).values())
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        return _agent_directory_conversation_record(agent, session_id=normalized_session_id)
    return None


def _agent_for_direct_session(session_id: str) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        agents = agent_directory_service.list_agents(include_archived=False)
    except Exception:
        return None
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("directSessionId") or "").strip() == normalized_session_id:
            return dict(agent)
    return None


_AGENT_SESSION_PURGE_MANIFEST = ".purge-manifest.json"
_AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX = ".cleanup.json"


def _path_is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except OSError:
        return False
    return bool(
        path.is_symlink()
        or attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _repair_stale_running_conversations(payload: dict[str, Any]) -> dict[str, Any]:
    """Clear persisted running state when no in-memory worker owns it."""

    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return payload

    changed = False
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        changed |= _repair_stale_running_conversation(conversation)
    if changed:
        payload["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    return payload


def _repair_stale_running_conversation(conversation: dict[str, Any]) -> bool:
    conversation_id = str(conversation.get("conversation_id") or "").strip()
    persisted_status = str(conversation.get("last_turn_status") or "").strip().lower()
    if persisted_status not in {"queued", "running", "stopping"}:
        return False
    if conversation_id and _is_session_running(conversation_id):
        return False
    recovered_at = _now_timestamp()
    summary = text_for(
        get_web_language(),
        zh="上一轮运行已被中断，当前会话已恢复为可继续状态。",
        en="The previous turn was interrupted. This session is ready to continue.",
    )
    if conversation.get("messages") and not _ledger_visible_messages_for_session(conversation_id):
        conversation["legacy_messages_preserved"] = True
    conversation["runtime_notices"] = _append_session_runtime_notice(
        conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": summary,
            "timestamp": recovered_at,
            "source": "conversation.turn_recovered",
            "turnId": _active_chat_turn_work_run_id_for_session(conversation_id),
            "previousStatus": persisted_status,
        },
    )
    conversation["last_turn_status"] = "ready"
    conversation["updated_at"] = recovered_at
    _release_stale_chat_turn_work_run(
        session_id=conversation_id,
        finished_at=recovered_at,
        summary=summary,
    )
    return True


def _normalize_session_runtime_notice(value: Any, *, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    message = str(value.get("message") or value.get("content") or "").strip()
    if not message:
        return None
    kind = str(value.get("kind") or value.get("type") or "").strip() or "runtime_notice"
    level = str(value.get("level") or value.get("severity") or "").strip().lower() or "info"
    if level not in {"info", "warning", "error", "success"}:
        level = "info"
    timestamp = str(value.get("timestamp") or value.get("createdAt") or value.get("created_at") or "").strip()
    notice_id = str(value.get("id") or value.get("noticeId") or "").strip()
    if not notice_id:
        notice_id = f"{kind}-{timestamp or index}"
    source = str(value.get("source") or value.get("eventCode") or "").strip()
    normalized: dict[str, Any] = {
        "id": notice_id,
        "kind": kind,
        "level": level,
        "message": message,
        "timestamp": timestamp,
        "source": source,
    }
    turn_id = str(value.get("turnId") or value.get("turn_id") or "").strip()
    if turn_id:
        normalized["turnId"] = turn_id
    previous_status = str(value.get("previousStatus") or value.get("previous_status") or "").strip()
    if previous_status:
        normalized["previousStatus"] = previous_status
    return normalized


def _append_session_runtime_notice(items: Any, notice: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalize_session_runtime_notices([*list(items or []), notice])


def _missing_llm_usage(*, recorded_at: str = "") -> dict[str, Any]:
    return {
        "source": "missing",
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cachedInputTokens": 0,
        "cacheReadInputTokens": 0,
        "cacheCreationInputTokens": 0,
        "uncachedInputTokens": 0,
        "cacheHitRate": 0.0,
        "provider": "",
        "model": "",
        "recordedAt": str(recorded_at or "").strip() or _now_timestamp(),
    }


def _not_called_cache_composition(*, recorded_at: str = "", reason: str = "") -> dict[str, Any]:
    return _normalize_session_cache_composition(
        {
            "recordedAt": str(recorded_at or "").strip() or _now_timestamp(),
            "source": "not_called",
            "segments": [
                {
                    "key": "missing",
                    "label": "not called",
                    "tokens": 1,
                    "status": str(reason or "not_called").strip() or "not_called",
                }
            ],
        }
    ) or {}


def _visible_session_runtime_notices(
    notices: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest_message_ts = max(
        (_timestamp_sort_key(str(message.get("timestamp") or "")) for message in list(messages or [])),
        default=0.0,
    )
    visible: list[dict[str, Any]] = []
    for notice in _normalize_session_runtime_notices(notices):
        notice_ts = _timestamp_sort_key(str(notice.get("timestamp") or ""))
        if notice_ts and latest_message_ts > notice_ts:
            continue
        visible.append(notice)
    return visible[-1:]


def _dedupe_turn_error_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_turn_errors: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for message in messages:
        metadata = message.get("metadata")
        if (
            isinstance(metadata, dict)
            and str(message.get("role") or "").strip().lower() == "assistant"
            and str(metadata.get("kind") or "").strip() == "turn_error"
        ):
            turn_id = str(metadata.get("turnId") or metadata.get("turn_id") or "").strip()
            if turn_id:
                dedupe_key = f"turn_error:{turn_id}"
                if dedupe_key in seen_turn_errors:
                    continue
                seen_turn_errors.add(dedupe_key)
        deduped.append(message)
    return deduped


def _message_turn_id(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(
        metadata.get("turnId")
        or metadata.get("turn_id")
        or message.get("turnId")
        or message.get("turn_id")
        or ""
    ).strip()


def _find_turn_scoped_assistant_message(messages: list[dict[str, Any]], turn_id: str) -> dict[str, Any] | None:
    normalized_turn_id = str(turn_id or "").strip()
    if not messages:
        return None
    if normalized_turn_id:
        for message in reversed(messages):
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            if _message_turn_id(message) == normalized_turn_id:
                return message
        user_index = -1
        for index, message in enumerate(messages):
            if str(message.get("role") or "").strip().lower() == "user" and _message_turn_id(message) == normalized_turn_id:
                user_index = index
        if user_index >= 0:
            for message in reversed(messages[user_index + 1 :]):
                if str(message.get("role") or "").strip().lower() != "assistant":
                    continue
                message_turn_id = _message_turn_id(message)
                if message_turn_id and message_turn_id != normalized_turn_id:
                    continue
                return message
        return None
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() == "assistant":
            return message
    return None


def _supervised_completion_marker_present(text: str) -> bool:
    normalized = str(text or "")
    return "SUPERVISED_FINAL_STATE:" in normalized or "SUPERVISED_INFEASIBLE_OUTCOME:" in normalized


def _normalize_latest_preview_messages(conversation_id: str, items: Any, *, scan_limit: int = 12) -> list[dict[str, Any]]:
    raw_items = list(items or [])
    total_count = len(raw_items)
    for reverse_index, raw in enumerate(reversed(raw_items[-scan_limit:]), start=1):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _sanitize_message_content(role, raw.get("content") or "")
        if not content or (role == "assistant" and _looks_like_runtime_failure_notice(content)):
            continue
        index = total_count - reverse_index + 1
        return [
            {
                "id": f"{conversation_id}-message-{index}",
                "role": role,
                "content": content,
                "timestamp": str(raw.get("timestamp") or "").strip(),
            }
        ]
    return []


def _normalize_session_kind(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"child", "supervised"}:
        return normalized
    return "main"


def _normalize_string_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in list(value or []):
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _history_message_turn_id(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        metadata.get("turnId")
        or metadata.get("turn_id")
        or item.get("turnId")
        or item.get("turn_id")
        or ""
    ).strip()


def _history_messages_for_agent_seed(
    items: Any,
    *,
    exclude_turn_id: str = "",
) -> list[dict[str, Any]]:
    """Build the prompt history view without transient runtime failure notices."""

    filtered: list[dict[str, Any]] = []
    drop_assistant_until_next_user = False
    normalized_exclude_turn_id = str(exclude_turn_id or "").strip()
    for item in normalize_chat_messages(items or []):
        if normalized_exclude_turn_id and _history_message_turn_id(item) == normalized_exclude_turn_id:
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "user":
            drop_assistant_until_next_user = False
        if _should_omit_message_from_agent_history(item):
            if role == "user":
                drop_assistant_until_next_user = True
            continue
        if role == "assistant" and drop_assistant_until_next_user:
            continue
        item = dict(item)
        attachments = _normalize_message_attachments(item.get("attachments") or item.get("imageAttachments") or [])
        if attachments:
            item["content"] = _message_content_with_attachment_summary(item.get("content") or "", attachments)
            item.pop("attachments", None)
        filtered.append(item)
    return filtered


def _lightweight_chat_payload_decision(
    context: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    if list(attachments or []):
        return False, "attachments"
    if list(context.get("session_references") or []):
        return False, "session_references"
    if context.get("skill_invocation"):
        return False, "skill_invocation"
    if normalize_active_skill_contract(context.get("active_skill_contract")):
        return False, "active_skill_contract"
    user_message_source = str(context.get("user_message_source") or "").strip()
    if user_message_source == "agent_inbox":
        return False, "agent_inbox"
    if user_message_source == "self_observation":
        return True, "self_observation"

    raw_message = str(context.get("raw_user_message") or "").strip()
    effective_message = str(context.get("user_message") or "").strip()
    message = raw_message or effective_message
    if not message:
        return False, "empty_message"
    return False, "unified_conversation_chain"


def _should_omit_message_from_agent_history(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    content = str(message.get("content") or "").strip()
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and str(metadata.get("kind") or "").strip() == "turn_error":
        return True
    if role == "user" and _is_system_authored_user_message_entry(message):
        return True
    attachments = _normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
    if role == "assistant":
        tool_calls = _normalize_message_tool_calls(
            message.get("tool_calls") or message.get("toolCalls") or message.get("tools") or []
        )
        if tool_calls:
            return False
    if role != "user":
        return role == "assistant" and (
            not content
            or _is_protocol_only_assistant_message(content)
            or _looks_like_provider_error_text(content)
            or _looks_like_runtime_failure_notice(content)
        )
    return not content and not attachments


def _is_protocol_only_assistant_message(content: Any) -> bool:
    raw = str(content or "").strip()
    if not raw:
        return True
    if _sanitize_message_content("assistant", raw):
        return False
    return bool(
        re.search(
            r"<\s*(?:/?state\b|/?invoke\b|/?parameter\b|/?active_components\b|[\w:.-]*tool_call\b|[^>\n]*dsml)",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _is_effective_user_message(message: Any) -> bool:
    return (
        _is_meaningful_task_goal(message)
        and not _is_contextual_confirmation_message(message)
        and not _looks_like_agent_inbox_protocol_message(message)
    )


def _latest_effective_user_message(messages: list[dict[str, Any]]) -> str:
    content, _index = _latest_effective_user_message_with_index(messages)
    return content


def _latest_effective_user_message_with_index(messages: list[dict[str, Any]]) -> tuple[str, int]:
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index]
        if not isinstance(item, dict):
            continue
        if not _is_real_user_message_entry(item):
            continue
        content = trim_lines(item.get("content") or "", max_lines=4)
        if _is_effective_user_message(content):
            return content, index
    return "", -1


def _latest_effective_user_messages(messages: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in reversed(messages):
        if not _is_real_user_message_entry(item):
            continue
        content = trim_lines(item.get("content") or "", max_lines=4)
        if not _is_effective_user_message(content):
            continue
        dedupe_key = re.sub(r"\s+", "", content)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        values.append(content)
        if len(values) >= max(1, limit):
            break
    return list(reversed(values))


def _latest_user_message_index_matching_goal(messages: list[dict[str, Any]], goal: Any) -> int:
    target = _task_goal_dedupe_key(goal)
    if not target:
        return -1
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index]
        if not isinstance(item, dict):
            continue
        if not _is_real_user_message_entry(item):
            continue
        content = trim_lines(item.get("content") or "", max_lines=4)
        if _task_goal_dedupe_key(content) == target:
            return index
    return -1


def _task_goal_dedupe_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _should_prefer_history_goal_over_active_task(
    active_task: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    *,
    existing_goal: str,
    history_goal: str,
    history_goal_index: int,
) -> bool:
    if not isinstance(active_task, dict):
        return False
    if not existing_goal or not history_goal:
        return False
    if _task_goal_dedupe_key(existing_goal) == _task_goal_dedupe_key(history_goal):
        return False
    existing_goal_index = _latest_user_message_index_matching_goal(messages, existing_goal)
    if existing_goal_index >= 0 and history_goal_index > existing_goal_index:
        return True
    metadata = active_task.get("metadata") if isinstance(active_task.get("metadata"), dict) else {}
    last_user_message = trim_lines(active_task.get("last_user_message") or "", max_lines=4)
    if (
        bool(metadata.get("last_user_message_filtered"))
        and last_user_message
        and not _is_effective_user_message(last_user_message)
        and _looks_like_tool_unavailable_claim(active_task.get("latest_summary") or "")
    ):
        return True
    return False


def _resolve_session_user_prompt(
    session_id: str,
    raw_message: Any,
    history_messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
) -> tuple[str, str]:
    prompt = str(raw_message or "").strip()
    if _is_continue_request(prompt):
        return prompt, "raw_continue"
    if _is_contextual_confirmation_message(prompt):
        return prompt, "raw_confirmation"
    if _is_effective_user_message(prompt):
        return prompt, "raw_meaningful"
    return prompt, "raw_dialogue"


def _build_contextual_confirmation_prompt(
    confirmation: str,
    goal: str,
    *,
    existing_task: dict[str, Any] | None = None,
) -> str:
    compact_confirmation = trim_lines(confirmation or "", max_lines=1)
    compact_goal = trim_lines(goal or "", max_lines=2)
    if not compact_confirmation or not compact_goal:
        return compact_goal or compact_confirmation
    lines = [
        f"用户确认：{compact_confirmation}",
        f"请基于已确认的当前目标继续执行：{compact_goal}",
    ]
    if isinstance(existing_task, dict):
        latest_summary = trim_lines(existing_task.get("latest_summary") or "", max_lines=2)
        next_action = trim_lines(existing_task.get("next_action") or "", max_lines=2)
        if latest_summary:
            lines.append(f"最近进展：{latest_summary}")
        if next_action:
            lines.append(f"下一步：{next_action}")
    lines.append("不要把这个确认短句当成新的任务标题，也不要只重复回答目标本身。")
    return "\n".join(lines)


def _looks_like_runtime_failure_notice(text: Any) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    notices = (
        "上一轮运行已被中断，当前会话已恢复为可继续状态",
        "当前 agent 正在处理上一项任务，本轮已进入队列",
        "the previous turn was interrupted. this session is ready to continue",
        "the agent is handling another task. this turn is queued",
    )
    return any(notice in value for notice in notices) or _looks_like_tool_unavailable_claim(value)


def _looks_like_tool_unavailable_claim(text: Any) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    zh_markers = (
        "无法执行任何工具操作",
        "所有工具当前都显示为不可用",
        "所有工具不可用",
        "无法生成图片",
    )
    en_markers = (
        "all tools are unavailable",
        "tools are unavailable",
        "cannot use any tools",
        "unable to use any tools",
    )
    has_tool_marker = (
        "工具" in value
        or "tool" in value
        or "image2_generate_tool" in value
    )
    return has_tool_marker and (
        any(marker in compact for marker in zh_markers)
        or any(marker in value for marker in en_markers)
    )


def _find_user_message_index_by_api_id(
    conversation_id: str,
    messages: list[dict[str, Any]],
    message_id: str,
) -> int:
    normalized_target = str(message_id or "").strip()
    if not normalized_target:
        return -1
    for index, item in enumerate(list(messages or []), start=1):
        api_id = str(item.get("id") or f"{conversation_id}-message-{index}").strip()
        if api_id == normalized_target and _is_real_user_message_entry(item):
            return index - 1
    return -1


def _latest_user_message_index(messages: list[dict[str, Any]]) -> int:
    for index in range(len(messages or []) - 1, -1, -1):
        if _is_real_user_message_entry(messages[index] or {}):
            return index
    return -1


def _sanitize_message_content(role: str, content: Any) -> str:
    text = str(content or "").strip()
    if str(role or "").strip().lower() != "assistant":
        return text
    return sanitize_assistant_visible_text(text)


def _session_reference_prompt_block(references: list[dict[str, Any]]) -> str:
    normalized = _normalize_session_references(references)
    if not normalized:
        return ""
    lines = [
        "[Session References]",
        "The user attached these conversation references as structured read-only context handles.",
        "You may query referenced conversation history with session_reference_query_tool.",
        "Do not send or notify another Agent only because a reference exists; use agent_message_tool only when the user's wording explicitly asks you to send/ask/notify that Agent.",
    ]
    for index, reference in enumerate(normalized, start=1):
        title = str(reference.get("title") or reference.get("sessionId") or "").strip()
        agent_label = str(reference.get("agentDisplayName") or reference.get("agentCode") or reference.get("agentId") or "").strip()
        summary = str(reference.get("summary") or "").strip()
        lines.append(
            f"- ref {index}: referenceId={reference.get('referenceId')}; sessionId={reference.get('sessionId')}; title={title}; agent={agent_label or 'unknown'}; allowed=query_only"
        )
        if summary:
            lines.append(f"  summary={summary}")
    return "\n".join(lines).strip()


def _message_content_with_attachment_summary(content: Any, attachments: list[dict[str, Any]]) -> str:
    text = str(content or "").strip()
    normalized = _normalize_message_attachments(attachments)
    if not normalized:
        return text
    lines = [text] if text else []
    lines.append("")
    lines.append("[图片附件摘要]")
    for index, attachment in enumerate(normalized, start=1):
        filename = str(attachment.get("filename") or attachment.get("artifactId") or f"image-{index}").strip()
        content_type = str(attachment.get("contentType") or "").strip()
        size_bytes = _coerce_nonnegative_int(attachment.get("sizeBytes") or 0)
        lines.append(f"- {filename} · {content_type or 'image'} · {size_bytes} bytes")
    return "\n".join(lines).strip()


def _build_lightweight_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    summary = _build_session_summary(conversation, hydrate_agent=False)
    return _build_session_detail_from_summary(conversation, summary, hydrate_agent=False)


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.agent_kernel.source_authority import source_ref

    return source_ref(kind, source_id, metadata)


def _pending_tool_governance_requests_for_session(agent_id: str, *, limit: int = 3) -> list[dict[str, Any]]:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return []
    try:
        from core.web.services import agent_tool_governance_service

        requests = agent_tool_governance_service.list_tool_governance_requests(
            agent_id=normalized_agent_id,
            status="pending_review",
            limit=limit,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to list pending tool governance requests for session detail. agent={normalized_agent_id}, limit={limit}, error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_GOVERNANCE",
        )
        return []
    result: list[dict[str, Any]] = []
    for item in requests:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "eventId": str(item.get("eventId") or "").strip(),
                "requestId": str(item.get("requestId") or item.get("eventId") or "").strip(),
                "kind": str(item.get("kind") or "tool_governance_request").strip(),
                "status": str(item.get("status") or "pending_review").strip(),
                "grantScope": str(item.get("grantScope") or "persistent").strip(),
                "sourceSessionId": str(item.get("sourceSessionId") or "").strip(),
                "sourceTurnId": str(item.get("sourceTurnId") or "").strip(),
                "targetAgentId": str(item.get("targetAgentId") or "").strip(),
                "targetAgentCode": str(item.get("targetAgentCode") or "").strip(),
                "targetAgentName": str(item.get("targetAgentName") or "").strip(),
                "proposedByAgentId": str(item.get("proposedByAgentId") or "").strip(),
                "proposedByAgentCode": str(item.get("proposedByAgentCode") or "").strip(),
                "proposedByAgentName": str(item.get("proposedByAgentName") or "").strip(),
                "policyDelta": item.get("policyDelta") if isinstance(item.get("policyDelta"), dict) else {},
                "reason": str(item.get("reason") or "").strip(),
                "authority": item.get("authority") if isinstance(item.get("authority"), dict) else {},
                "riskLevel": str(item.get("riskLevel") or "low").strip(),
                "riskTags": list(item.get("riskTags") or []),
                "requiresApproval": bool(item.get("requiresApproval", True)),
                "approvalReason": str(item.get("approvalReason") or "").strip(),
                "createdAt": str(item.get("createdAt") or "").strip(),
                "resolvedAt": str(item.get("resolvedAt") or "").strip(),
                "resolvedBy": str(item.get("resolvedBy") or "").strip(),
                "resolutionNote": str(item.get("resolutionNote") or "").strip(),
                "appliedToolPolicyId": str(item.get("appliedToolPolicyId") or "").strip(),
                "temporaryGrant": item.get("temporaryGrant") if isinstance(item.get("temporaryGrant"), dict) else {},
                "after": item.get("after") if isinstance(item.get("after"), dict) else {},
            }
        )
    return result


def _session_last_llm_usage(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(list(messages or [])):
        if str((message or {}).get("role") or "").strip().lower() != "assistant":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        normalized = _normalize_turn_llm_usage(metadata.get("llmUsage") or metadata.get("llm_usage"))
        if normalized is not None:
            return normalized
    return None


def _message_list_content_preview(messages: list[dict[str, Any]], *, limit: int = 4) -> str:
    parts: list[str] = []
    for item in list(messages or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "message").strip() or "message"
        content = _compact_preview_text(item.get("content") or "", max_lines=2, max_chars=120)
        if not content:
            tool_parts = []
            for tool_call in list(item.get("toolCalls") or item.get("tool_calls") or [])[:2]:
                if isinstance(tool_call, dict):
                    tool_parts.append(
                        _compact_preview_text(
                            tool_call.get("summary")
                            or tool_call.get("resultPreview")
                            or tool_call.get("result_preview")
                            or tool_call.get("name")
                            or "",
                            max_lines=1,
                            max_chars=80,
                        )
                    )
            content = "; ".join(part for part in tool_parts if part)
        if content:
            parts.append(f"{role}: {content}")
    return _compact_preview_text(" | ".join(parts), max_lines=1, max_chars=240)


def _active_task_content_preview(active_task: Any) -> str:
    task = _normalize_session_active_task(active_task)
    if not isinstance(task, dict):
        return ""
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("latest_summary"),
        task.get("next_action"),
    ]
    return _compact_preview_text(" | ".join(str(item or "") for item in parts if str(item or "").strip()), max_lines=1, max_chars=240)


_SESSION_LLM_PAYLOAD_TRACE_TEXT_FIELDS = {
    "traceId",
    "recordedAt",
    "phase",
    "role",
    "profileId",
    "provider",
    "model",
    "sessionId",
    "turnId",
    "agentId",
    "llmSlot",
    "modelId",
    "promptPurpose",
    "dialogueChainMode",
    "transport",
    "selectedProtocol",
    "protocolSource",
}
_SESSION_LLM_PAYLOAD_TRACE_INT_FIELDS = {
    "schemaVersion",
    "messageCount",
    "toolCount",
    "imageBlockCount",
}
_SESSION_LLM_PAYLOAD_TRACE_MAP_FIELD_KEYS = {
    "payloadShape": {
        "inputItemCount",
        "messagePayloadCount",
        "toolDefinitionCount",
        "imageBlockCount",
        "hasTools",
        "usesResponsesPayload",
    },
    "promptCache": {
        "promptCacheMode",
        "promptCacheEnabled",
        "promptCachePayloadEnabled",
        "promptCachePartitionHash",
        "promptCachePartitionChars",
        "cacheControlMessageCount",
    },
    "thinking": {
        "thinkingRequested",
        "thinkingType",
        "thinkingDisplay",
    },
    "contextAssembly": {
        "turnId",
        "messageCount",
        "includedMessageCount",
        "historyMessageCount",
        "toolResultCount",
        "contextTokenEstimate",
        "tokenBudget",
        "truncated",
    },
}


def _normalize_llm_payload_trace_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for item_key, item_value in value.items():
        key = str(item_key or "").strip()
        if not key:
            continue
        counts[key] = _coerce_nonnegative_int(item_value)
    return counts


def _normalize_llm_payload_trace_map(value: Any, allowed_keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe_item: dict[str, Any] = {}
    for key in allowed_keys:
        item_value = value.get(key)
        if item_value in (None, ""):
            continue
        if isinstance(item_value, bool):
            safe_item[key] = item_value
        elif isinstance(item_value, (int, float)):
            safe_item[key] = _coerce_nonnegative_int(item_value)
        elif isinstance(item_value, str):
            text = item_value.strip()
            if text:
                safe_item[key] = text
    return safe_item


def _weighted_token_allocation(total_tokens: int, weights: list[int]) -> list[int]:
    total = _coerce_nonnegative_int(total_tokens)
    normalized_weights = [max(0, _coerce_nonnegative_int(weight)) for weight in weights]
    weight_total = sum(normalized_weights)
    if total <= 0 or weight_total <= 0:
        return [0 for _ in normalized_weights]
    allocations: list[int] = []
    used = 0
    for index, weight in enumerate(normalized_weights):
        if weight <= 0:
            allocations.append(0)
            continue
        if index == len(normalized_weights) - 1:
            value = max(0, total - used)
        else:
            value = int((total * weight) // weight_total)
        allocations.append(value)
        used += value
    remainder = total - sum(allocations)
    index = 0
    while remainder > 0 and allocations:
        allocations[index % len(allocations)] += 1
        remainder -= 1
        index += 1
    return allocations


def _cache_average_from_usage(cache_usage: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(cache_usage, dict):
        return {
            "inputTokens": 0,
            "cachedInputTokens": 0,
            "observedTurnCount": 0,
        }
    input_tokens = _coerce_nonnegative_int(
        cache_usage.get("totalInputTokens")
        or cache_usage.get("averageInputTokens")
        or 0
    )
    cached_tokens = min(
        _coerce_nonnegative_int(
            cache_usage.get("totalCachedInputTokens")
            or cache_usage.get("averageCachedInputTokens")
            or 0
        ),
        input_tokens,
    ) if input_tokens else 0
    return {
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "observedTurnCount": _coerce_nonnegative_int(
            cache_usage.get("totalObservedTurnCount")
            or cache_usage.get("averageObservedTurnCount")
            or 0
        ),
    }


def _session_last_cache_composition(
    conversation: dict[str, Any],
    *,
    llm_usage: dict[str, Any] | None,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
    normalized_last_cache_composition: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    existing = normalized_last_cache_composition or _normalize_session_cache_composition(
        conversation.get("lastCacheComposition") or conversation.get("last_cache_composition")
    )
    if existing is not None:
        return _enrich_session_cache_composition(
            existing,
            context_composition=context_composition,
            average_cache=average_cache,
        )
    usage = _normalize_turn_llm_usage(llm_usage)
    if usage is None:
        return None
    return _build_session_cache_composition(
        "",
        usage,
        context_composition=context_composition,
        average_cache=average_cache,
    )


def _estimate_session_context_tokens(character_count: int, tool_call_count: int) -> int:
    # Conservative mixed Chinese/English approximation plus a small per-message/tool overhead.
    return max(0, int((max(0, character_count) + 2) // 3) + max(0, tool_call_count) * 12)


def _message_list_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        total += len(str(item.get("content") or ""))
        total += len(str(item.get("thought") or ""))
        for tool_call in list(item.get("toolCalls") or item.get("tool_calls") or []):
            if isinstance(tool_call, dict):
                total += len(str(tool_call.get("name") or ""))
                total += len(str(tool_call.get("summary") or ""))
                total += len(str(tool_call.get("resultPreview") or tool_call.get("result_preview") or ""))
                total += len(str(tool_call.get("error") or ""))
    return total


def _active_task_context_chars(active_task: Any) -> int:
    task = _normalize_session_active_task(active_task)
    if not isinstance(task, dict):
        return 0
    if not _is_task_tool_backed_active_task(task):
        return 0
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("latest_summary"),
        task.get("next_action"),
        " ".join(str(item) for item in list(task.get("read_files") or [])[:8]),
        " ".join(str(item) for item in list(task.get("changed_files") or [])[:8]),
    ]
    return len("\n".join(str(item or "") for item in parts if str(item or "").strip()))


_AGENT_CONTEXT_SEGMENT_LABELS = {
    "agent_runtime": "agent runtime rules",
    "research_organization": "research organization context",
    "prompt_template": "agent prompt template",
    "project_rules": "project rules",
    "project_agent_registry": "agent registry",
    "agent_messages": "agent messages",
}

_AGENT_CONTEXT_SEGMENT_CATEGORIES = {
    "agent_runtime": "agent_spec",
    "research_organization": "project_context",
    "prompt_template": "agent_spec",
    "agent_prompt_snapshot": "system_prompt",
    "project_rules": "developer_instructions",
    "project_agent_registry": "agent_registry",
    "agent_messages": "agent_messages",
}

_CONTEXT_PROMPT_CATEGORIES = {
    "current_user": "current_user",
    "history": "history",
    "active_task": "task_state",
    "agent_context": "agent_context",
    "dynamic_runtime_context": "runtime_context",
    "guidance": "operator_guidance",
    "skill": "skill_context",
    "active_skill": "skill_context",
    "attachments": "attachments",
}


def _agent_context_prompt_category(key: str) -> str:
    normalized = str(key or "").strip()
    return _AGENT_CONTEXT_SEGMENT_CATEGORIES.get(normalized, "agent_context")


def _context_prompt_category(key: str) -> str:
    normalized = str(key or "").strip()
    if normalized in _AGENT_CONTEXT_SEGMENT_CATEGORIES:
        return _agent_context_prompt_category(normalized)
    return _CONTEXT_PROMPT_CATEGORIES.get(normalized, normalized or "context")


def _agent_context_manifest_segments(
    runtime_context_segments: list[dict[str, Any]] | None,
    *,
    dynamic_runtime_context_included: bool,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    segments: list[dict[str, Any]] = []
    previews: dict[str, str] = {}
    for index, item in enumerate(list(runtime_context_segments or [])):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        block = str(item.get("block") or "").strip()
        if not key or not block:
            continue
        placement = str(item.get("placement") or "").strip()
        is_static = placement == "cache_prefix"
        is_dynamic = placement == "volatile_turn"
        if not is_static and not is_dynamic:
            continue
        included = bool(is_static or (is_dynamic and dynamic_runtime_context_included))
        segment = _context_segment(
            key,
            _agent_context_segment_label(key),
            content=block,
            chars=_coerce_nonnegative_int(item.get("chars") or len(block)),
            item_count=1,
            status="included" if included else "omitted",
            source="context_engine",
            description=(
                "ContextEngine prompt segment seeded into the stable system prefix."
                if is_static
                else "ContextEngine turn-local prompt segment."
            ),
            kind=_agent_context_prompt_category(key),
            lifecycle="stable" if is_static else "turn",
            authority=82 if is_static else 58,
            volatility=15 if is_static else 88,
            relevance=76,
            placement="system_prefix" if is_static else "before_current_user",
            cache_policy="cacheable" if is_static else "volatile",
            retention="persist" if is_static else "current_turn_only",
            included_in_model_input=included,
            content_hash=str(item.get("hash") or "").strip(),
        )
        segment["promptCategory"] = _agent_context_prompt_category(key)
        segment["segmentKind"] = "prompt_source"
        segment["accuracy"] = "manifest"
        segment["order"] = index
        segments.append(segment)
        preview = _compact_preview_text(block, max_lines=3, max_chars=240)
        if preview:
            previews[key] = preview
    return segments, previews


def _session_context_limit(conversation: dict[str, Any] | None = None) -> int:
    return _coerce_nonnegative_int(_session_context_limit_payload(conversation).get("limit") or 0)


def _session_context_limit_payload(conversation: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        cfg = get_config()
        model_payload = _conversation_agent_dialogue_context_window_payload(cfg, conversation)
        model_limit = _coerce_nonnegative_int(model_payload.get("limit") or 0)
        compression_limit = int(getattr(cfg.context_compression, "max_token_limit", 0) or 0)
        limit = _first_positive_int(model_limit, compression_limit, 128000)
        if model_limit:
            return {
                **model_payload,
                "limit": limit,
                "source": "agent_dialogue_model",
            }
        if compression_limit:
            return {"limit": limit, "source": "context_compression_fallback", "modelId": "", "agentId": ""}
        return {"limit": limit, "source": "static_fallback", "modelId": "", "agentId": ""}
    except Exception:
        return {"limit": 128000, "source": "static_fallback", "modelId": "", "agentId": ""}


def _first_positive_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            return parsed
    return 0


def _normalize_project_paths(items: Any, *, existing_only: bool) -> list[str]:
    project_root = PROJECT_ROOT.resolve()
    paths: list[str] = []
    for raw in list(items or []):
        value = str(raw or "").strip()
        if not value or value in {".", "./"}:
            continue
        candidate = (project_root / value).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError:
            continue
        if existing_only:
            if not candidate.exists() or not candidate.is_file():
                continue
        elif candidate.exists() and candidate.is_dir():
            continue
        normalized = candidate.relative_to(project_root).as_posix()
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _normalize_project_path(value: Any, *, existing_only: bool) -> str:
    paths = _normalize_project_paths([value], existing_only=existing_only)
    return paths[0] if paths else ""


def _merge_project_paths(*groups: list[str], limit: int = 8) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for raw in list(group or []):
            value = str(raw or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
    if limit > 0:
        return merged[-limit:]
    return merged


_SESSION_TASK_CONTEXT_TOOL_NAMES = {
    "task_create_tool",
    "task_start_tool",
    "plan_update_tool",
    "task_complete_tool",
}


def _is_task_tool_name(name: Any) -> bool:
    return str(name or "").strip() in _SESSION_TASK_CONTEXT_TOOL_NAMES


def _result_has_task_context_tool(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    for tool_call in _extract_chat_tool_calls(result):
        if _is_task_tool_name(_tool_call_name(tool_call)):
            return True
    return False


def _is_task_tool_backed_active_task(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    source = str(metadata.get("source") or "").strip()
    return source == "task_tool"


def _set_or_clear_session_active_task(conversation: dict[str, Any], task: dict[str, Any] | None) -> None:
    if task is not None:
        conversation["active_task"] = task
        conversation.pop("activeTask", None)
        return
    conversation.pop("active_task", None)
    conversation.pop("activeTask", None)


def _latest_assistant_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if not _is_real_user_message_entry(item):
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if not _is_real_user_message_entry(item):
            continue
        return trim_lines(item.get("content") or "", max_lines=4)
    return ""


def _latest_real_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if not _is_real_user_message_entry(item):
            continue
        return trim_lines(item.get("content") or "", max_lines=4)
    return ""


def _message_metadata_kind(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(metadata.get("kind") or "").strip()


def _is_system_authored_user_message_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return _message_metadata_kind(item) == "hot_restart_resume"


def _is_real_user_message_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return not (_is_agent_inbox_message_entry(item) or _is_system_authored_user_message_entry(item))


def _compact_preview_text(text: Any, *, max_lines: int = 3, max_chars: int = 180) -> str:
    lines = [re.sub(r"\s+", " ", str(line or "")).strip() for line in str(text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return ""
    preview = " ".join(visible_lines[:max_lines]).strip()
    if len(preview) <= max_chars:
        return preview
    return f"{preview[: max_chars - 1].rstrip()}..."


def _latest_message_timestamp(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        timestamp = str(item.get("timestamp") or "").strip()
        if timestamp:
            return timestamp
    return ""


def _conversation_is_read_only(conversation: dict[str, Any]) -> bool:
    archive_state = conversation.get("archive_state") or conversation.get(
        "archiveState"
    )
    archived = (
        isinstance(archive_state, dict)
        and str(archive_state.get("status") or "").strip().lower() == "archived"
    )
    return bool(
        conversation.get("read_only")
        or conversation.get("readOnly")
        or archived
    )


def _ensure_session_mutable(
    session_id: str,
    *,
    conversation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionNotFoundError("Session not found")
    target = conversation
    if target is None:
        with _CHAT_STATE_LOCK:
            payload = load_chat_state(PROJECT_ROOT)
            target = _find_conversation_entry(payload, normalized_session_id)
    if target is None:
        raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
    if _conversation_is_read_only(target):
        raise SessionValidationError(
            text_for(
                get_web_language(),
                zh="该会话已归档并处于只读状态，不能再修改。",
                en="This session is archived and read-only; it cannot be modified.",
            )
        )
    return target


def _root_session_id_for_conversations(session_id: str, conversations: list[dict[str, Any]]) -> str:
    normalized = str(session_id or "").strip()
    for item in list(conversations or []):
        if str(item.get("id") or item.get("conversation_id") or "").strip() != normalized:
            continue
        root_id = str(item.get("rootSessionId") or item.get("root_session_id") or "").strip()
        if root_id:
            return root_id
        parent_id = str(item.get("parentSessionId") or item.get("parent_session_id") or "").strip()
        return parent_id or normalized
    return normalized


def _latest_user_message_id(conversation_id: str, messages: list[dict[str, Any]]) -> str:
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index] or {}
        if not _is_real_user_message_entry(item):
            continue
        return str(item.get("id") or f"{conversation_id}-message-{index + 1}").strip()
    return ""


def _session_fixed_model_choice(session_id: str) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    agent_id = _session_agent_id_snapshot(normalized_session_id)
    agent = get_agent(agent_id, include_archived=False) if agent_id else None
    fallback_detail: dict[str, Any] | None = None
    if agent is None:
        fallback_detail = get_session_detail(normalized_session_id, message_limit=0, transcript_scope="none")
        if fallback_detail is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        fallback_agent_id = str(fallback_detail.get("agentId") or "").strip()
        agent = get_agent(fallback_agent_id, include_archived=False) if fallback_agent_id else None
    model_ref = str(
        agent_dialogue_model_id(agent)
        or (fallback_detail or {}).get("dialogueModelId")
        or ""
    ).strip()
    if not model_ref:
        raise SessionValidationError("当前会话的 Agent 尚未绑定对话模型。")
    selected = next(
        (
            choice
            for choice in _session_llm_model_choices()
            if model_ref
            in {
                str(choice.get("modelRef") or "").strip(),
                str(choice.get("modelId") or "").strip(),
            }
        ),
        None,
    )
    if selected is None:
        raise SessionValidationError(f"当前 Agent 绑定的模型不在模型库中：{model_ref}。")
    result = copy.deepcopy(selected)
    result["modelRef"] = str(result.get("modelRef") or result.get("modelId") or model_ref).strip()
    return result


def _initial_session_reasoning_effort(agent: dict[str, Any] | None, model: dict[str, Any]) -> str:
    supported = [
        normalize_reasoning_effort(value)
        for value in list(model.get("reasoningEffortValues") or [])
    ]
    supported = [value for value in dict.fromkeys(supported) if value]
    agent_default = normalize_reasoning_effort(_session_agent_reasoning_effort(agent))
    model_default = normalize_reasoning_effort(model.get("defaultReasoningEffort"))
    return next(
        (value for value in (agent_default, model_default) if value in supported),
        supported[0] if supported else "",
    )


def _initialized_session_reasoning_effort(session_id: str) -> tuple[bool, str]:
    normalized_session_id = str(session_id or "").strip()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        if "reasoning_effort" not in conversation:
            return False, ""
        return True, normalize_reasoning_effort(conversation.get("reasoning_effort"))


def _ensure_session_reasoning_effort_initialized(session_id: str) -> str:
    normalized_session_id = str(session_id or "").strip()
    initialized, current = _initialized_session_reasoning_effort(normalized_session_id)
    if initialized:
        return current
    model = _session_fixed_model_choice(normalized_session_id)
    agent_id = _session_agent_id_snapshot(normalized_session_id)
    agent = get_agent(agent_id, include_archived=False) if agent_id else None
    if agent is None:
        detail = get_session_detail(normalized_session_id, message_limit=0, transcript_scope="none")
        if detail is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        fallback_agent_id = str(detail.get("agentId") or "").strip()
        agent = get_agent(fallback_agent_id, include_archived=False) if fallback_agent_id else None
    initial = _initial_session_reasoning_effort(agent, model)
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        if "reasoning_effort" in conversation:
            return normalize_reasoning_effort(conversation.get("reasoning_effort"))
        conversation["reasoning_effort"] = initial
        conversation["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    return initial


def _session_reasoning_effort_snapshot(session_id: str) -> str:
    initialized, current = _initialized_session_reasoning_effort(session_id)
    if initialized:
        return current
    return _ensure_session_reasoning_effort_initialized(session_id)


def update_session_reasoning_effort(
    session_id: str,
    *,
    reasoning_effort: str,
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    selected = _session_fixed_model_choice(normalized_session_id)
    supported_efforts = {
        normalize_reasoning_effort(value)
        for value in list(selected.get("reasoningEffortValues") or [])
        if normalize_reasoning_effort(value)
    }
    normalized_effort = normalize_reasoning_effort(reasoning_effort)
    if normalized_effort not in supported_efforts:
        raise SessionValidationError(
            f"模型 {selected.get('label') or selected.get('modelId')} 不支持推理强度 {normalized_effort or '-'}。"
        )
    with _CHAT_STATE_LOCK:
        if _is_session_running(normalized_session_id):
            raise SessionBusyError("会话运行中，不能切换推理强度。")
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        _ensure_session_mutable(
            normalized_session_id,
            conversation=conversation,
        )
        conversation["reasoning_effort"] = normalized_effort
        conversation["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    try:
        record_runtime_scene_event(
            "conversation",
            "reasoning_effort",
            "conversation.reasoning_effort.updated",
            level="info",
            outcome="updated",
            message="Session reasoning effort updated without changing the Agent model binding.",
            fields={
                "sessionId": normalized_session_id,
                "modelRef": str(selected.get("modelRef") or selected.get("modelId") or "").strip(),
                "reasoningEffortRequested": normalized_effort,
                "reasoningEffortAdapter": str(selected.get("reasoningAdapter") or "none").strip(),
                "source": "session_record",
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene reasoning effort log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    return get_session_llm_options(normalized_session_id)


def _default_session_dialogue_model_id() -> str:
    try:
        config = get_config()
    except Exception:
        return ""
    try:
        profile = config.llm.get_profile(profile_id=DEFAULT_SESSION_AGENT_PROFILE_ID)
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
        if str(model_id or "").strip():
            return str(model_id or "").strip()
    except Exception:
        pass
    model_library = getattr(config.llm, "model_library", {}) or {}
    if isinstance(model_library, dict):
        items = model_library.items()
    else:
        items = []
    for model_id, item in items:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        if model:
            return str(model_id or "").strip()
    return ""


def _session_prompt_cache_partition(
    *,
    session_id: str,
    agent_id: str = "",
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    llm_model_id: str = "",
    model_id: str = "",
    prompt_template_id: str = "",
    prompt_snapshot_hash: str = "",
) -> str:
    """Build a short stable provider cache shard for the ordinary chat flow."""

    normalized_model = str(llm_model_id or model_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_slot = str(llm_slot or SESSION_LLM_SLOT_DIALOGUE).strip() or SESSION_LLM_SLOT_DIALOGUE
    normalized_template = str(prompt_template_id or "").strip()
    normalized_snapshot_hash = str(prompt_snapshot_hash or "").strip()
    if normalized_agent_id:
        raw_parts = [
            SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC,
            normalized_agent_id,
            normalized_slot,
            normalized_model,
            normalized_template,
            normalized_snapshot_hash,
        ]
        raw = "|".join(raw_parts)
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
        return developer_sandbox.sandbox_prompt_cache_partition(f"chat-agent-static-{digest}", surface="chat", project_root=PROJECT_ROOT)

    raw_parts = [
        SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
        str(session_id or "").strip(),
        normalized_slot,
        normalized_model,
    ]
    raw = "|".join(raw_parts)
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    return developer_sandbox.sandbox_prompt_cache_partition(f"chat-session-{digest}", surface="chat", project_root=PROJECT_ROOT)


def _session_prompt_cache_scope(*, agent_id: str = "") -> str:
    if str(agent_id or "").strip():
        return SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC
    return SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK


def _session_prompt_cache_log_fields(*, scope: str, partition: str) -> dict[str, Any]:
    normalized_scope = str(scope or "").strip()
    normalized_partition = str(partition or "").strip()
    return {
        "promptCacheScope": normalized_scope,
        "promptCachePartition": normalized_partition,
        "promptCachePartitionHash": _short_hash(normalized_partition),
        "promptCachePartitionChars": len(normalized_partition),
        "promptCacheSessionFallback": normalized_scope == SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    }


def _is_session_busy_for_delete(conversation_id: str, conversation: dict[str, Any]) -> bool:
    phase = _conversation_phase(conversation_id, conversation)
    return phase in {"queued", "running", "stopping", "paused"}


def _is_session_running(session_id: str) -> bool:
    with _RUNNING_SESSIONS_LOCK:
        return session_id in _RUNNING_SESSION_IDS


def has_running_sessions() -> bool:
    """Return whether any web chat session turn is currently active."""

    with _RUNNING_SESSIONS_LOCK:
        return bool(_RUNNING_SESSION_IDS)


def active_session_has_write_leases() -> bool:
    for run in list_active_session_work_runs():
        leases = set(leases_for_snapshot(run))
        if leases.intersection({WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE}):
            return True
    return False


def _check_chat_turn_lease_decision(leases: list[str]):
    active_runs = [
        snapshot
        for snapshot in (
            load_evolution_active_run_snapshot("self"),
            load_evolution_active_run_snapshot("supervised"),
        )
        if isinstance(snapshot, dict)
    ]
    return check_lease_conflicts(
        WorkRunLeaseRequest(run_kind="chat_turn", leases=leases),
        active_runs,
    )


def _localize_lease_conflict(reason: str, *, lang: str) -> str:
    fallback = str(reason or "").strip()
    return text_for(
        lang,
        zh=f"当前资源正在被另一条运行占用，请等待它收束后再继续。{fallback}",
        en=f"Another active run holds a conflicting resource lease. Wait for it to finish before continuing. {fallback}",
    ).strip()


def _replacement_active_chat_turn_id(*, exclude_turn_id: str = "") -> str:
    excluded = str(exclude_turn_id or "").strip()
    with _RUNNING_SESSIONS_LOCK:
        for turn_id in _SESSION_ACTIVE_TURN_IDS.values():
            normalized = str(turn_id or "").strip()
            if normalized and normalized != excluded:
                return normalized
    return ""


def _source_collection_stage_task_turn_metadata(messages: list[dict[str, Any]], turn_id: str = "") -> dict[str, str]:
    normalized_turn_id = str(turn_id or "").strip()
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
            continue
        message_turn_id = _message_turn_id(message)
        if normalized_turn_id and message_turn_id and message_turn_id != normalized_turn_id:
            continue
        team_id = str(metadata.get("teamId") or "").strip()
        task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
        if not team_id or not task_id:
            continue
        return {
            "teamId": team_id,
            "runId": str(metadata.get("runId") or "").strip(),
            "taskId": task_id,
            "stageId": str(metadata.get("stageId") or "").strip(),
            "agentId": str(metadata.get("agentId") or "").strip(),
            "agentRole": str(metadata.get("agentRole") or "").strip(),
            "turnId": message_turn_id,
        }
    return {}


def _set_session_running(
    session_id: str,
    is_running: bool,
    *,
    turn_id: str = "",
    leases: list[str] | None = None,
) -> None:
    with _RUNNING_SESSIONS_LOCK:
        if is_running:
            _RUNNING_SESSION_IDS.add(session_id)
            if turn_id:
                _SESSION_ACTIVE_TURN_IDS[session_id] = turn_id
            if leases is not None:
                _SESSION_ACTIVE_TURN_LEASES[session_id] = list(leases)
        else:
            if not turn_id:
                _RUNNING_SESSION_IDS.discard(session_id)
                _SESSION_ACTIVE_TURN_IDS.pop(session_id, None)
                _SESSION_ACTIVE_TURN_LEASES.pop(session_id, None)
                return
            if _SESSION_ACTIVE_TURN_IDS.get(session_id) == turn_id:
                _RUNNING_SESSION_IDS.discard(session_id)
                _SESSION_ACTIVE_TURN_IDS.pop(session_id, None)
                _SESSION_ACTIVE_TURN_LEASES.pop(session_id, None)


def _is_session_turn_current(session_id: str, turn_id: str) -> bool:
    if not turn_id:
        return True
    with _RUNNING_SESSIONS_LOCK:
        return _SESSION_ACTIVE_TURN_IDS.get(session_id) == turn_id





_SESSION_TURN_SCHEDULER = SessionTurnScheduler(
    agent_key_for_context=_session_scheduler_agent_key,
    session_key_for_context=_session_scheduler_session_key,
    max_active_per_agent=_SESSION_AGENT_MAX_ACTIVE_TURNS,
    now=_perf_counter,
    record_event=_record_scheduler_event_adapter,
    mark_queued=lambda context, position: _mark_session_turn_queued(context, queue_position=position),
    mark_dequeued=lambda context: _mark_session_turn_dequeued(context),
    is_session_running=lambda session_id: _is_session_running(session_id),
    is_session_turn_current=lambda session_id, turn_id: _is_session_turn_current(session_id, turn_id),
)

















def _supervised_role_for_runtime_context(context: dict[str, Any], agent_instance: dict[str, Any] | None) -> str:
    if str(context.get("user_message_source") or "").strip() != "supervised_evolution":
        return ""
    candidates: list[Any] = [
        context.get("message_metadata"),
        context.get("supervised_context"),
        (agent_instance or {}).get("metadata") if isinstance(agent_instance, dict) else {},
    ]
    for payload in candidates:
        if not isinstance(payload, dict):
            continue
        for key in ("supervisedRole", "role", "supervised_role"):
            role = str(payload.get(key) or "").strip()
            if role:
                return role
    return ""


def _supervised_workspace_override_path(context: dict[str, Any]) -> Path | None:
    """Return a per-turn candidate worktree override for supervised hidden sessions."""

    if str(context.get("user_message_source") or "").strip() != "supervised_evolution":
        return None
    candidates: list[Any] = [
        context.get("message_metadata"),
        context.get("supervised_context"),
    ]
    raw_path = ""
    for payload in candidates:
        if not isinstance(payload, dict):
            continue
        for key in ("workspaceOverride", "workspace_override", "toolWorkspaceOverride", "tool_workspace_override"):
            value = str(payload.get(key) or "").strip()
            if value:
                raw_path = value
                break
        if raw_path:
            break
    if not raw_path:
        return None
    try:
        candidate_path = Path(raw_path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise SessionValidationError(f"Invalid supervised workspace override: {raw_path}") from exc
    if not candidate_path.exists():
        raise SessionValidationError(f"Supervised workspace override does not exist: {candidate_path}")
    if not candidate_path.is_dir():
        raise SessionValidationError(f"Supervised workspace override is not a directory: {candidate_path}")
    return candidate_path


def _source_collection_stage_task_context_metadata(context: dict[str, Any]) -> dict[str, str]:
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    if str(metadata.get("kind") or "").strip() != SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
        return {}
    team_id = str(metadata.get("teamId") or "").strip()
    task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
    if not team_id or not task_id:
        return {}
    return {
        "teamId": team_id,
        "runId": str(metadata.get("runId") or "").strip(),
        "stageId": str(metadata.get("stageId") or "").strip(),
        "taskId": task_id,
        "agentId": str(metadata.get("agentId") or "").strip(),
        "agentRole": str(metadata.get("agentRole") or "").strip(),
    }


_SOURCE_COLLECTION_STAGE_TASK_CONTINUATION_METADATA_KEYS = (
    "kind",
    "sourceSurface",
    "teamId",
    "runId",
    "stageId",
    "agentId",
    "agentRole",
    "sourceCollectionStageTaskId",
    "sourceCollectionStageTaskKey",
    "sourceContextMode",
    "writebackContract",
    "taskToolRequired",
    "taskChecklist",
)


def _source_collection_stage_task_continuation_metadata(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Carry a stage-task contract across a bounded chain of explicit continue turns."""

    for message in reversed(list(messages or [])):
        if not isinstance(message, dict) or str(message.get("role") or "").strip().lower() != "user":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() == SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
            team_id = str(metadata.get("teamId") or "").strip()
            task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
            if team_id and task_id:
                return {
                    key: copy.deepcopy(metadata[key])
                    for key in _SOURCE_COLLECTION_STAGE_TASK_CONTINUATION_METADATA_KEYS
                    if key in metadata
                }
            return {}
        if _is_continue_request(message.get("content")):
            continue
        return {}
    return {}


def _source_collection_stage_task_continuation_prompt(metadata: dict[str, Any]) -> str:
    if not isinstance(metadata, dict) or metadata.get("sourceCollectionStageContinuation") is not True:
        return ""
    if str(metadata.get("kind") or "").strip() != SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
        return ""
    team_id = str(metadata.get("teamId") or "").strip()
    run_id = str(metadata.get("runId") or "").strip()
    stage_id = str(metadata.get("stageId") or "").strip()
    task_id = str(metadata.get("sourceCollectionStageTaskId") or "").strip()
    if not team_id or not task_id:
        return ""
    required_tools = _source_collection_stage_task_required_tool_names({"message_metadata": metadata})
    lines = [
        "用户请求继续当前资料搜集阶段任务。请沿用现有 checklist 和已完成进度，不要新建或切换任务。",
        f"- team_id: {team_id}",
        f"- run_id: {run_id}",
        f"- stage_id: {stage_id}",
        f"- task_id: {task_id}",
    ]
    if required_tools:
        lines.append(f"- required_tools: {', '.join(required_tools)}")
    source_context_mode = str(metadata.get("sourceContextMode") or "").strip().lower()
    extraction_evidence_continuation = (
        stage_id == "extraction"
        and source_context_mode in {"evidence", "retry_evidence"}
    )
    lines.extend(
        [
            "本阶段 checklist 已由后端绑定；直接沿用阶段上下文，只补尚未完成的分页或指定缺口，不要调用通用 task_list_tool、task_create_tool 或 task_update_tool 复制清单。",
            (
                "证据补全时可使用 web_fetch_tool，但仅抓取上下文已给出的 sourceUrl 或 DOI；"
                "不要扩展检索方向、搜索新候选或抓取 file:///localhost。每页先补证并分批回写，再读取下一页；"
                "单条抓取失败才标记 needs_more_info，并继续处理其他候选。"
                if extraction_evidence_continuation
                else "续跑阶段不要调用 web_fetch_tool、research_knowledge_query_tool 或通用记忆搜索；现有证据不足的候选直接标记 needs_more_info。"
            ),
            "优先分批调用 source_collection_stage_writeback_tool 产生可累计结果，再更新 checklist；以服务端 coverageSummary 和 completionGate 为准。",
        ]
    )
    return "\n".join(lines)


def _session_task_workspace_for_turn(
    context: dict[str, Any],
    *,
    session_workspace: str | Path,
    default_workspace: str | Path,
) -> Path:
    """Keep stage-task checklists fresh without clearing an Agent's durable task state."""

    stage_task = _source_collection_stage_task_context_metadata(context)
    task_id = str(stage_task.get("taskId") or "").strip()
    if not task_id:
        return Path(default_workspace)
    return Path(session_workspace) / "stage_tasks" / _safe_session_workspace_token(task_id)


def _source_collection_stage_task_required_tool_names(context: dict[str, Any]) -> list[str]:
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    contract = metadata.get("writebackContract") if isinstance(metadata.get("writebackContract"), dict) else {}
    checklist = contract.get("taskChecklist") or metadata.get("taskChecklist") or []
    names: list[str] = []
    for item in list(checklist or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("requiredTool") or "").strip()
        if name and name not in names:
            names.append(name)
    writeback_tool = str(contract.get("toolName") or "").strip()
    if writeback_tool and writeback_tool not in names:
        names.append(writeback_tool)
    return names






def _skill_invocation_payload(command: SkillSlashCommand | None) -> dict[str, Any] | None:
    if command is None:
        return None
    return {
        "command": command.command,
        "args": command.args,
        **skill_descriptor_for_log(command.skill),
        "_skill": command.skill,
    }


def _active_skill_contract_from_invocation(
    invocation: Any,
    *,
    turn_id: str = "",
) -> dict[str, Any] | None:
    contract = build_active_skill_contract(
        invocation,
        activated_at=_now_timestamp(),
        activated_turn_id=turn_id,
        scope="task",
    )
    return contract


def _active_skill_contract_from_conversation(conversation: Any) -> dict[str, Any] | None:
    if not isinstance(conversation, dict):
        return None
    return refresh_active_skill_contract_status(
        conversation.get("active_skill_contract") or conversation.get("activeSkillContract")
    )


def _skill_runtime_context_from_invocation(invocation: Any) -> str:
    if not isinstance(invocation, dict):
        return ""
    skill = invocation.get("_skill")
    if skill is None:
        return ""
    return build_skill_runtime_context(
        skill,
        command=str(invocation.get("command") or ""),
        args=str(invocation.get("args") or ""),
    )


def _active_skill_runtime_context_from_contract(contract: Any) -> str:
    return build_active_skill_runtime_context(contract)


def _record_session_skill_command_event(
    session_id: str,
    *,
    turn_id: str = "",
    invocation: Any = None,
    outcome: str = "routed",
) -> None:
    if not isinstance(invocation, dict):
        return
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "command": str(invocation.get("command") or "").strip(),
        "skillName": str(invocation.get("skillName") or "").strip(),
        "skillPath": str(invocation.get("skillPath") or "").strip(),
        "skillHash": str(invocation.get("skillHash") or "").strip(),
        "skillContentLength": int(invocation.get("skillContentLength") or 0),
        "argsLength": len(str(invocation.get("args") or "")),
    }
    child_payload = {
        "session_id": fields["sessionId"],
        "turn_id": fields["turnId"],
        "command": fields["command"],
        "skill_name": fields["skillName"],
        "skill_hash": fields["skillHash"],
        "skill_content_length": fields["skillContentLength"],
        "args_length": fields["argsLength"],
        "outcome": str(outcome or "routed"),
    }
    try:
        record_runtime_scene_event(
            "conversation",
            "skill_command",
            "conversation.skill_command.routed",
            level="info",
            outcome=outcome,
            message="Chat slash skill command routed.",
            fields=fields,
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-skill-commands.jsonl",
            child_log_payload=child_payload,
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene skill command log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _attach_session_prompt_cache_metadata(
    result: Any,
    *,
    prompt_cache_scope: str,
    prompt_cache_partition: str,
    llm_model_id: str,
) -> Any:
    if not isinstance(result, dict):
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    metadata.setdefault("promptCacheScope", str(prompt_cache_scope or "").strip())
    metadata.setdefault("promptCachePartition", str(prompt_cache_partition or "").strip())
    metadata.setdefault("promptCachePartitionHash", _short_hash(prompt_cache_partition))
    metadata.setdefault("promptCachePartitionChars", len(str(prompt_cache_partition or "").strip()))
    metadata.setdefault(
        "promptCacheSessionFallback",
        str(prompt_cache_scope or "").strip() == SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    )
    metadata.setdefault("llmModelId", str(llm_model_id or "").strip())
    result["metadata"] = metadata
    usage = result.get("llm_usage")
    if isinstance(usage, dict):
        usage.setdefault("promptCacheScope", metadata.get("promptCacheScope") or "")
        usage.setdefault("promptCachePartition", metadata.get("promptCachePartition") or "")
        usage.setdefault("llmModelId", metadata.get("llmModelId") or "")
    return result




def _agent_message_tool_sent_to_source(
    tool_calls: list[dict[str, Any]],
    *,
    source_agent_id: str,
) -> bool:
    normalized_source_agent_id = str(source_agent_id or "").strip()
    if not normalized_source_agent_id:
        return False
    for tool_call in list(tool_calls or []):
        if not isinstance(tool_call, dict):
            continue
        if str(tool_call.get("name") or "").strip() != "agent_message_tool":
            continue
        result_payload = _parse_agent_message_tool_result(tool_call)
        if not _agent_message_tool_result_succeeded(result_payload):
            continue
        if str(result_payload.get("targetAgentId") or "").strip() == normalized_source_agent_id:
            return True
    return False


def _parse_agent_message_tool_result(tool_call: dict[str, Any]) -> dict[str, Any]:
    for key in ("resultPreview", "result_preview", "summary"):
        raw = str(tool_call.get(key) or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _agent_message_tool_result_succeeded(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if not infer_tool_business_success(payload):
        return False
    return bool(str(payload.get("targetAgentId") or "").strip())


def _looks_like_agent_message_delivery_confirmation(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if len(normalized) > 240:
        return False
    return bool(
        re.search(
            r"(已(?:将|把).{0,80}(?:发送|发给|转发|投递).{0,80}(?:成功|完成)|消息投递成功|投递成功|发送成功|已发送给)",
            normalized,
        )
    )


def _extract_missing_agent_llm_model_id(message: Any) -> str:
    value = str(message or "").strip()
    marker = "model not found in model library:"
    lowered = value.lower()
    marker_index = lowered.find(marker)
    if marker_index < 0:
        return ""
    return value[marker_index + len(marker):].strip().split()[0].strip("`'\".,;")



def _make_local_runtime_error_chat_message(turn_error: dict[str, Any], *, turn_id: str = "") -> dict[str, Any]:
    timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
    error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    reason_summary = str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip()
    reason_detail = str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip()
    visible_message = str(turn_error.get("message") or "").strip()
    message = _make_chat_message(
        "assistant",
        visible_message,
        metadata={
            "kind": "turn_error",
            "errorType": error_type,
            "turnId": str(turn_error.get("turn_id") or turn_error.get("turnId") or turn_id or "").strip(),
            "recoverable": bool(turn_error.get("recoverable")),
            "providerFailure": False,
            "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
            "reasonSummary": reason_summary,
            "reasonDetail": reason_detail,
            "httpStatus": _coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or None,
            "provider": str(turn_error.get("provider") or "").strip(),
            "providerHost": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
            "providerErrorType": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
            "providerErrorMessage": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
            "model": str(turn_error.get("model") or "").strip(),
            "chainStage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
            "eventCode": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
            "traceId": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
            "protocol": str(turn_error.get("protocol") or "").strip(),
        },
    )
    message["timestamp"] = timestamp
    return message



def _ensure_assistant_visible_text(content: Any, *, result: Any = None, lang: str | None = None) -> str:
    cleaned = _sanitize_message_content("assistant", content)
    if cleaned and _looks_like_provider_error_text(cleaned):
        return _user_visible_failure_summary(cleaned, lang=lang or get_web_language())
    if cleaned:
        return cleaned
    if isinstance(result, dict):
        for key in ("error", "message", "blocked_reason", "required_user_input", "recommended_next_action", "next_action"):
            fallback = _sanitize_message_content("assistant", result.get(key) or "")
            if fallback:
                if _looks_like_provider_error_text(fallback):
                    return _user_visible_failure_summary(fallback, lang=lang or get_web_language())
                return fallback
        tool_trace = result.get("tool_trace") or result.get("tool_calls") or []
        if tool_trace:
            return text_for(
                lang or get_web_language(),
                zh="本轮只记录了工具调用，没有生成可见回答；请发送“继续”让 agent 汇总结果。",
                en='This turn only recorded tool calls and did not produce a visible reply. Send "continue" to summarize the result.',
            )
    return text_for(
        lang or get_web_language(),
        zh=_NO_VISIBLE_REPLY_ZH,
        en=_NO_VISIBLE_REPLY_EN,
    )


def _make_chat_message(
    role: str,
    content: str,
    tool_calls: list[Any] | None = None,
    *,
    thought: str = "",
    mental_snapshot: dict[str, Any] | None = None,
    feedback_events: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": str(role or "").strip().lower(),
        "content": _ensure_assistant_visible_text(content) if str(role or "").strip().lower() == "assistant" else str(content or "").strip(),
        "timestamp": _now_timestamp(),
    }
    cleaned_thought = _sanitize_thought_text(thought)
    if cleaned_thought:
        message["thought"] = cleaned_thought
    normalized_snapshot = _normalize_mental_snapshot(mental_snapshot)
    if normalized_snapshot is not None:
        message["mental_snapshot"] = normalized_snapshot
    normalized_tool_calls = _normalize_persisted_tool_calls(tool_calls or [])
    if normalized_tool_calls:
        message["tool_calls"] = normalized_tool_calls
    normalized_feedback_events = _normalize_persisted_feedback_events(feedback_events or [])
    if normalized_feedback_events:
        message["feedback_events"] = normalized_feedback_events
    normalized_attachments = _normalize_message_attachments(attachments or [])
    if normalized_attachments:
        message["attachments"] = normalized_attachments
    normalized_references = _normalize_session_references(references or [])
    if normalized_references:
        message["references"] = normalized_references
    if isinstance(metadata, dict) and metadata:
        message["metadata"] = dict(metadata)
        if message["role"] == "assistant" and str(metadata.get("kind") or "").strip() == "turn_error":
            message["content"] = _complete_turn_error_visible_content(message.get("content") or "", metadata)
    return message


def _record_session_cycle_message(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    _append_session_workspace_log(
        session_id,
        message,
        event=event,
        status=status,
        active_task=active_task,
    )
    try:
        role = str(message.get("role") or "").strip() or "message"
        content = _sanitize_message_content(role, message.get("content") or "")
        record_runtime_scene_conversation_event(
            session_id,
            role,
            content,
            message=message,
            event=event,
            status=status,
            tool_calls=_normalize_message_tool_calls(
                message.get("tool_calls") or message.get("toolCalls") or []
            ),
            active_task=active_task,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene conversation log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _submit_session_cycle_message_projection(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    turn_id: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    _SESSION_CYCLE_PROJECTION_EXECUTOR.submit(
        _run_session_cycle_message_projection,
        str(session_id or "").strip(),
        copy.deepcopy(message),
        event=str(event or "").strip(),
        status=str(status or "").strip(),
        turn_id=str(turn_id or "").strip(),
        active_task=copy.deepcopy(active_task) if isinstance(active_task, dict) else None,
    )


def _record_session_turn_started_event(
    session_id: str,
    *,
    turn_id: str,
    leases: list[str] | None = None,
    user_message: str = "",
    raw_user_message: str = "",
    user_message_source: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    attachment_summary = _safe_attachment_log_summary(attachments or [])
    try:
        record_runtime_scene_event(
            "conversation",
            "turn",
            "conversation.turn.started",
            message="Web chat turn started.",
            level="info",
            outcome="running",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "leaseCount": len(list(leases or [])),
                "userMessageChars": len(str(user_message or "")),
                "rawUserMessageChars": len(str(raw_user_message or "")),
                "userMessageSource": str(user_message_source or "").strip(),
                "attachmentCount": len(attachment_summary),
                "attachments": attachment_summary,
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene chat turn start log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_scheduled_event(context: dict[str, Any]) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    submit_timing_fields = dict(context.get("submit_timing_fields") or {})
    submit_started_at = context.get("submit_started_at_monotonic")
    if submit_started_at is not None:
        submit_timing_fields["submitElapsedBeforeScheduleLogMs"] = _elapsed_ms_between(submit_started_at)
    _record_session_turn_lifecycle_event(
        session_id,
        "scheduled",
        turn_id=turn_id,
        outcome="queued",
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "historyMessageCount": len(list(context.get("history_messages") or [])),
            "mentalModelEnabled": _normalize_optional_bool(context.get("mental_model_enabled")),
            "userMessageLength": len(str(context.get("user_message") or "")),
            "userMessageSource": str(context.get("user_message_source") or "").strip(),
            "clientSubmissionId": str(context.get("client_submission_id") or "").strip(),
            "attachmentCount": len(_normalize_message_attachments(context.get("attachments") or [])),
            **submit_timing_fields,
        },
    )


def _record_session_turn_accepted_event(
    context: dict[str, Any],
    submit_timing_fields: dict[str, Any],
) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    fields = dict(submit_timing_fields or {})
    submit_started_at = context.get("submit_started_at_monotonic")
    if submit_started_at is not None:
        fields["submitTotalMs"] = _elapsed_ms_between(submit_started_at)
    _record_session_turn_lifecycle_event(
        session_id,
        "accepted",
        turn_id=turn_id,
        outcome="accepted",
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "clientSubmissionId": str(context.get("client_submission_id") or "").strip(),
            **fields,
        },
    )


def _record_session_user_message_filtered_event(
    session_id: str,
    *,
    turn_id: str = "",
    reason: str = "",
    message: str = "",
    source: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "message_filtered",
            "conversation.user_message_filtered",
            level="warning",
            outcome="ignored",
            message="Ignored a non-meaningful user message for prompt/task derivation.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "reason": str(reason or "").strip(),
                "source": str(source or "").strip(),
                "messageLength": len(str(message or "")),
                "questionMarkCount": str(message or "").count("?"),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_turn_lifecycle_event(
    session_id: str,
    phase: str,
    *,
    turn_id: str = "",
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    normalized_phase = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(phase or "event").strip()).strip("._-") or "event"
    normalized_turn_id = str(turn_id or "").strip()
    event_fields = {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        **(fields or {}),
    }
    child_payload = {
        "session_id": normalized_session_id,
        "turn_id": normalized_turn_id,
        "phase": normalized_phase,
        "outcome": str(outcome or "").strip() or "observed",
        **(fields or {}),
    }
    try:
        record_runtime_scene_event(
            "conversation",
            f"turn_{normalized_phase}",
            f"conversation.turn.{normalized_phase}",
            level=level,
            outcome=outcome,
            message=f"Conversation turn {normalized_phase.replace('_', ' ')}.",
            fields=event_fields,
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-turns.jsonl",
            child_log_payload=child_payload,
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene turn lifecycle log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _session_turn_prepare_timing_log_fields(timings: dict[str, Any]) -> dict[str, Any]:
    """Keep turn-start telemetry below the runtime-scene field cap.

    ``worker_started`` already has enough identity and runtime fields to hit the
    telemetry field limit. Emit preparation timings in a dedicated event rather
    than silently dropping the measurements that explain pre-LLM latency.
    """

    keys = (
        "totalPrepareMs",
        "sessionWorkspaceMs",
        "agentDirectorySyncMs",
        "agentLookupMs",
        "promptSnapshotMs",
        "lightweightChatDecisionMs",
        "agentContextBuildMs",
        "workspacePolicyMs",
        "llmKeyEnvSyncMs",
        "agentLlmResolveMs",
        "llmKeyEnvSyncedCount",
        "llmKeyEnvAlreadyPresentCount",
        "llmKeyEnvMissingCount",
    )
    return {
        key: timings[key]
        for key in keys
        if key in timings and isinstance(timings[key], (bool, int, float))
    }


def _record_session_delete_event(
    phase: str,
    *,
    session_id: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    normalized_phase = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(phase or "event").strip()).strip("._-") or "event"
    try:
        record_runtime_scene_event(
            "conversation",
            f"session_delete_{normalized_phase}",
            f"session.delete.{normalized_phase}",
            level=level,
            outcome=outcome,
            message="Session delete lifecycle event.",
            fields={
                "sessionId": normalized_session_id,
                "source": "manual_session_action",
                **(fields or {}),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-delete.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "phase": normalized_phase,
                "outcome": outcome,
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_list_loaded_event(
    *,
    session_count: int,
    conversation_count: int,
    agent_count: int,
    elapsed_ms: int,
    cache_hit: bool = False,
    cache_age_ms: int = 0,
    cache_ttl_ms: int = 0,
    waited_for_inflight: bool = False,
) -> None:
    cache_expired = bool(cache_hit and cache_ttl_ms > 0 and cache_age_ms > cache_ttl_ms)
    try:
        record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.loaded",
            level="info",
            outcome="observed",
            message="Session list loaded through read-only lightweight indexes.",
            fields={
                "sessionCount": int(session_count),
                "conversationCount": int(conversation_count),
                "agentCount": int(agent_count),
                "elapsedMs": int(elapsed_ms),
                "readOnly": True,
                "hydrateAgent": False,
                "repair": False,
                "cacheHit": bool(cache_hit),
                "cacheAgeMs": max(0, int(cache_age_ms)),
                "cacheTtlMs": max(0, int(cache_ttl_ms)),
                "cacheExpired": cache_expired,
                "servedStaleMatchingSignature": cache_expired,
                "waitedForInflight": bool(waited_for_inflight),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_list_prewarm_event(
    *,
    status: str,
    reason: str,
    elapsed_ms: int,
    session_count: int = 0,
    error_type: str = "",
    error_message: str = "",
) -> None:
    normalized_status = str(status or "").strip().lower() or "observed"
    try:
        message = (
            "Session list cache prewarm failed before the first user request."
            if normalized_status == "failed"
            else "Session list cache prewarm completed outside the user request path."
        )
        record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.prewarm",
            level="warning" if normalized_status == "failed" else "info",
            outcome=normalized_status,
            message=message,
            fields={
                "status": normalized_status,
                "reason": trim_lines(reason, max_lines=1) or "startup",
                "elapsedMs": max(0, int(elapsed_ms)),
                "sessionCount": max(0, int(session_count)),
                "readOnly": True,
                "hydrateAgent": False,
                "cacheWarmup": True,
                "errorType": str(error_type or "").strip(),
                "errorMessage": trim_lines(error_message, max_lines=2),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_list_query_event(
    *,
    result_count: int,
    matched_count: int,
    total_count: int,
    limit: int,
    cursor: int,
    elapsed_ms: int,
    has_query: bool,
    has_agent_filter: bool,
    has_kind_filter: bool,
    has_state_filter: bool,
    sort: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "session_list",
            "session.list.query",
            level="info",
            outcome="observed",
            message="Session list query served a paginated lightweight index page.",
            fields={
                "resultCount": int(result_count),
                "matchedCount": int(matched_count),
                "totalCount": int(total_count),
                "limit": int(limit),
                "cursor": int(cursor),
                "elapsedMs": int(elapsed_ms),
                "hasQuery": bool(has_query),
                "hasAgentFilter": bool(has_agent_filter),
                "hasKindFilter": bool(has_kind_filter),
                "hasStateFilter": bool(has_state_filter),
                "sort": str(sort or "").strip(),
                "readOnly": True,
                "hydrateAgent": False,
            },
            lifecycle=False,
        )
    except Exception:
        return


def _conversation_turn_log_path(session_id: str, turn_id: str, file_name: str) -> str:
    session_token = _safe_session_workspace_token(session_id)
    turn_token = _safe_session_workspace_token(turn_id or "turn")
    file_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(file_name or "trace_events.jsonl")).strip("._-")
    return f"sessions/{session_token}/turns/{turn_token}/{file_token or 'trace_events.jsonl'}"


def _record_session_turn_subpackage_event(
    session_id: str,
    turn_id: str,
    file_name: str,
    payload: dict[str, Any],
    *,
    phase: str,
    event_code: str,
    level: str = "info",
    outcome: str = "observed",
    message: str = "",
) -> str:
    path = _conversation_turn_log_path(session_id, turn_id, file_name)
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "chatTurnLogPath": path,
    }
    try:
        record_runtime_scene_event(
            "conversation",
            phase,
            event_code,
            level=level,
            outcome=outcome,
            message=message or event_code,
            fields=fields,
            child_log_path=path,
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                **(payload or {}),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene chat turn subpackage log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    return path


def _record_session_turn_trace_event(
    session_id: str,
    turn_id: str,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    status: str = "",
    summary: str = "",
) -> None:
    _record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "trace_events.jsonl",
        {
            "kind": str(kind or "event").strip(),
            "status": str(status or "").strip(),
            "summary": trim_lines(summary or "", max_lines=3),
            "payload": payload if isinstance(payload, dict) else {},
        },
        phase=f"turn_trace_{kind or 'event'}",
        event_code=f"conversation.turn.trace.{re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(kind or 'event')).strip('._-') or 'event'}",
        outcome=status or "observed",
        message=f"Conversation turn trace {kind or 'event'}.",
    )


def _record_session_execution_registry_event(
    session_id: str,
    turn_id: str,
    entry_type: str,
    status: str,
    *,
    owner: str = "main",
    details: dict[str, Any] | None = None,
) -> None:
    _record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "execution_registry.jsonl",
        {
            "entry_type": str(entry_type or "runtime").strip(),
            "owner": str(owner or "main").strip(),
            "status": str(status or "").strip(),
            "details": details if isinstance(details, dict) else {},
        },
        phase=f"turn_execution_{entry_type or 'runtime'}",
        event_code="conversation.turn.execution_registry",
        outcome=status or "observed",
        message=f"Conversation turn execution registry: {entry_type or 'runtime'}.",
    )


def _record_session_turn_visible_message(
    session_id: str,
    turn_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
) -> None:
    role = str(message.get("role") or "").strip()
    _record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "visible_messages.jsonl",
        {
            "event": str(event or "message").strip(),
            "status": str(status or "").strip(),
            "role": role,
            "content": _sanitize_message_content(role, message.get("content") or ""),
            "message": message,
        },
        phase="turn_visible_message",
        event_code="conversation.turn.visible_message",
        outcome=status or "observed",
        message="Conversation turn visible message persisted.",
    )


def _record_session_turn_result_log(
    session_id: str,
    turn_id: str,
    *,
    status: str,
    summary: str,
    recovery_pointer: dict[str, Any] | None = None,
) -> None:
    _record_session_turn_subpackage_event(
        session_id,
        turn_id,
        "turn_result.jsonl",
        {
            "status": str(status or "").strip(),
            "summary": trim_lines(summary or "", max_lines=6),
            "recovery_pointer": recovery_pointer if isinstance(recovery_pointer, dict) else {},
        },
        phase="turn_result",
        event_code="conversation.turn.result",
        outcome=status or "observed",
        message="Conversation turn result persisted.",
    )


def _record_session_message_edit_resubmit_event(
    session_id: str,
    *,
    target_message_id: str,
    turn_id: str,
    truncated_count: int,
    original_content: str,
    edited_content: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "message_edit_resubmit",
            "conversation.message_edited_resubmitted",
            level="info",
            outcome="accepted",
            message="Latest user message edited and resubmitted.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "messageId": str(target_message_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "truncatedMessageCount": max(0, int(truncated_count or 0)),
                "originalPreview": trim_lines(original_content, max_lines=2),
                "editedPreview": trim_lines(edited_content, max_lines=2),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-edits.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "message_id": str(target_message_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                "truncated_message_count": max(0, int(truncated_count or 0)),
                "original_preview": trim_lines(original_content, max_lines=2),
                "edited_preview": trim_lines(edited_content, max_lines=2),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene message edit log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_message_edit_resubmit_rejected_event(
    session_id: str,
    *,
    target_message_id: str,
    reason: str,
    latest_message_id: str = "",
    target_preview: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "message_edit_resubmit_rejected",
            "conversation.message_edit_resubmit_rejected",
            level="warning",
            outcome="rejected",
            message="Rejected a message edit because only the latest user message can be edited and resent.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "messageId": str(target_message_id or "").strip(),
                "latestMessageId": str(latest_message_id or "").strip(),
                "reason": str(reason or "").strip(),
                "targetPreview": trim_lines(target_preview, max_lines=2),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-edits.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "message_id": str(target_message_id or "").strip(),
                "latest_message_id": str(latest_message_id or "").strip(),
                "reason": str(reason or "").strip(),
                "target_preview": trim_lines(target_preview, max_lines=2),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene rejected edit log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _compact_tool_loop_failure_hint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    http_match = re.search(r"\bHTTP\s+(\d{3})\b", text, flags=re.IGNORECASE)
    if http_match:
        return f"HTTP {http_match.group(1)}"
    lowered = text.lower()
    if "无法连接" in text or "connection" in lowered or "connect" in lowered:
        return "无法连接"
    if "重定向" in text or "redirect" in lowered:
        return "重定向被拦截"
    if "内容为空" in text or "empty" in lowered:
        return "内容为空"
    if _looks_like_tool_call_failure_summary(text):
        return trim_lines(text, max_lines=1)
    return ""


_TOOL_RESULT_FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "transportStatus": ("transportStatus", "transport_status"),
    "semanticStatus": ("semanticStatus", "semantic_status"),
    "failureClass": ("failureClass", "failure_class"),
    "exitCode": ("exitCode", "exit_code", "returncode", "return_code"),
    "timedOut": ("timedOut", "timed_out"),
    "resultKind": ("resultKind", "result_kind"),
    "truncated": ("truncated",),
    "originalLength": ("originalLength", "original_length"),
}


def _first_present_mapping_value(source: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in source and source.get(key) is not None:
            return source.get(key)
    return None


def _copy_tool_result_fact_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    if not isinstance(source, dict):
        return
    for canonical, aliases in _TOOL_RESULT_FACT_ALIASES.items():
        value = _first_present_mapping_value(source, aliases)
        if value is None or value == "":
            continue
        if canonical in {"exitCode", "originalLength"}:
            numeric = _coerce_tool_number(value)
            if numeric is None:
                continue
            target[canonical] = numeric
            continue
        if canonical in {"timedOut", "truncated"}:
            if isinstance(value, str):
                target[canonical] = value.strip().lower() in {"1", "true", "yes", "y", "on"}
            else:
                target[canonical] = bool(value)
            continue
        target[canonical] = str(value).strip()


def _sandbox_terminal_result_facts(value: Any) -> dict[str, Any]:
    """Extract explicit terminal facts from the new sandbox tool result envelope."""

    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(str(value or "").lstrip("\ufeff").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    if not isinstance(payload, dict):
        return {}
    terminal_session_id = str(payload.get("terminalSessionId") or "").strip()
    if not terminal_session_id:
        return {}
    result: dict[str, Any] = {"terminalSessionId": terminal_session_id}
    for key in ("status", "terminalStatus"):
        status = str(payload.get(key) or "").strip()
        if status:
            result["terminalStatus"] = status
            break
    if "sessionOpen" in payload:
        result["sessionOpen"] = bool(payload.get("sessionOpen"))
    formatted_output = _trim_tool_detail_text(payload.get("formattedOutput") or "", max_chars=1200, max_lines=10)
    if formatted_output:
        result["formattedOutput"] = formatted_output
    for key in ("exitCode", "timedOut", "truncated", "originalLength", "durationMs"):
        if key in payload:
            result[key] = payload[key]
    return result


def _trim_tool_detail_text(value: Any, *, max_chars: int = 1200, max_lines: int = 12) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "\n" not in text and "\r" not in text:
        if len(text) > max_chars:
            return text[: max_chars - 1].rstrip() + "…"
        return text
    lines = text.splitlines()
    text = "\n".join(line.rstrip() for line in lines[:max_lines]).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _safe_tool_argument_details(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    details: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key or key.startswith("_") or key.lower() in {"api_key", "apikey", "token", "secret", "password"}:
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            details[key] = raw_value
            continue
        if isinstance(raw_value, str):
            details[key] = _trim_tool_detail_text(raw_value, max_chars=420, max_lines=4)
            continue
        if isinstance(raw_value, (list, tuple)):
            details[key] = [_trim_tool_detail_text(item, max_chars=220, max_lines=2) for item in list(raw_value)[:8]]
            continue
        if isinstance(raw_value, dict):
            nested: dict[str, Any] = {}
            for nested_key, nested_value in list(raw_value.items())[:16]:
                nested_name = str(nested_key or "").strip()
                if not nested_name or nested_name.startswith("_") or nested_name.lower() in {"api_key", "apikey", "token", "secret", "password"}:
                    continue
                nested[nested_name] = _trim_tool_detail_text(nested_value, max_chars=220, max_lines=2)
            details[key] = nested
            continue
        details[key] = _trim_tool_detail_text(raw_value, max_chars=220, max_lines=2)
    return details


def _coerce_tool_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value and value not in {float("inf"), float("-inf")}:
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed != parsed or parsed in {float("inf"), float("-inf")}:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _close_previous_running_status_events(events: Any, current_name: str) -> list[dict[str, Any]]:
    normalized_current_name = str(current_name or "").strip()
    normalized_events: list[dict[str, Any]] = []
    for item in _normalize_message_feedback_events(events):
        entry = dict(item)
        if (
            str(entry.get("kind") or "").strip() == "status"
            and str(entry.get("name") or "").strip() != normalized_current_name
            and str(entry.get("status") or "").strip().lower() in {"running", "pending"}
        ):
            entry["status"] = "done"
        normalized_events.append(entry)
    return normalized_events


def _session_events_have_terminal_turn(events: Any, turn_id: str) -> bool:
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return False
    for event in events or []:
        event_turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if event_turn_id != normalized_turn_id:
            continue
        event_type = str(getattr(event, "event_type", "") or "").strip()
        if event_type in {EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED}:
            return True
    return False


def _build_message_timeline_items(
    *,
    message_id: str,
    content: Any = "",
    feedback_events: Any = None,
    streaming: bool = False,
    include_assistant_text: bool = True,
    lang: str | None = None,
) -> list[dict[str, Any]]:
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return []
    normalized_feedback_events = _normalize_message_feedback_events(feedback_events or [])
    if not normalized_feedback_events:
        return []
    return build_conversation_timeline_items(
        message_id=normalized_message_id,
        content=content,
        feedback_events=normalized_feedback_events,
        streaming=streaming,
        lang=str(lang or "").strip() or get_web_language(),
        include_assistant_text=include_assistant_text,
    )


def _assistant_projection_text_key(value: Any) -> str:
    return "".join(str(value or "").split())


def _session_turn_item_base_id(session_id: str, turn_id: str) -> str:
    normalized_session_id = str(session_id or "").strip() or "session"
    normalized_turn_id = str(turn_id or "").strip() or "current"
    return f"{normalized_session_id}-turn-{normalized_turn_id}"


def _session_turn_agent_message_item_id(session_id: str, turn_id: str) -> str:
    return f"{_session_turn_item_base_id(session_id, turn_id)}-agent-message"


def _build_terminal_error_turn_item(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    content: Any,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized_metadata = dict(metadata or {})
    normalized_turn_id = str(
        turn_id
        or normalized_metadata.get("turnId")
        or normalized_metadata.get("turn_id")
        or ""
    ).strip()
    item_id = f"{_session_turn_item_base_id(session_id, normalized_turn_id)}-error"
    diagnostic_summary = {
        key: normalized_metadata[key]
        for key in (
            "reasonCode",
            "reasonSummary",
            "reasonDetail",
            "httpStatus",
            "providerErrorType",
            "provider",
            "model",
            "chainStage",
            "eventCode",
            "traceId",
            "protocol",
            "retryable",
        )
        if normalized_metadata.get(key) not in (None, "")
    }
    return {
        "version": 2,
        "id": f"{item_id}:0",
        "type": "error",
        "sessionId": str(session_id or "").strip(),
        "turnId": normalized_turn_id,
        "itemId": item_id,
        "revision": 0,
        "sequence": 1,
        "kind": "error",
        "phase": "turn_failed",
        "status": "failed",
        "provisional": False,
        "terminal": True,
        "messageId": str(message_id or "").strip(),
        "source": "session_turn_error",
        "text": str(content or "").strip(),
        "diagnosticSummary": diagnostic_summary,
        "metadata": {"turnId": normalized_turn_id},
    }


def _terminal_error_turn_item(items: Any) -> dict[str, Any] | None:
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("type") or item.get("kind") or "").strip() == "error"
            and item.get("terminal") is True
            and item.get("provisional") is not True
        ):
            return item
    return None


def _session_turn_assistant_markdown_text(cells: list[Any]) -> str:
    text_parts: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if str(cell.get("kind") or "").strip() != "assistant_markdown":
            continue
        text = _sanitize_message_content("assistant", cell.get("text") or "")
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)


def _session_turn_item_from_codex_cell(
    *,
    session_id: str,
    turn_id: str,
    message_id: str,
    cell: dict[str, Any],
    index: int,
    source: str,
) -> dict[str, Any] | None:
    cell_kind = str(cell.get("kind") or "").strip()
    if cell_kind == "assistant_markdown":
        return None
    item_type = _session_turn_item_type_from_codex_cell(cell_kind)
    if not item_type:
        return None
    cell_id = str(cell.get("id") or "").strip()
    suffix = cell_id or f"{item_type}-{index}"
    return _compact_codex_record(
        {
            "id": f"{_session_turn_item_base_id(session_id, turn_id)}-{item_type}-{_short_hash(suffix) or index}",
            "type": item_type,
            "status": str(cell.get("status") or "completed").strip() or "completed",
            "turnId": turn_id,
            "messageId": message_id,
            "source": source,
            "sourceCellId": cell_id,
            "sourceCellKind": cell_kind,
            "title": str(cell.get("title") or "").strip(),
            "summary": str(cell.get("summary") or "").strip(),
            "text": str(cell.get("text") or "").strip(),
            "sourceItemId": str(cell.get("sourceItemId") or "").strip(),
            "operationIds": list(cell.get("operationIds") or []),
        }
    )


def _session_turn_item_type_from_codex_cell(cell_kind: str) -> str:
    if cell_kind == "reasoning_summary":
        return "reasoning"
    if cell_kind == "tool_call":
        return "tool_call"
    if cell_kind == "status":
        return "status"
    if cell_kind == "error_notice":
        return "error"
    if cell_kind == "stream_tail":
        return "status"
    return ""


def _codex_transcript_operation_sources(
    message_id: str,
    feedback_events: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for event in feedback_events:
        source = dict(event)
        if _is_non_diagnostic_runtime_status_source(source):
            continue
        source["_operationId"] = _codex_operation_id(message_id, source, len(sources) + 1)
        source["_sourceKind"] = "feedback"
        sources.append(source)
    if sources:
        return sources
    for index, tool_call in enumerate(tool_calls, start=1):
        source = dict(tool_call)
        source.setdefault("kind", "tool")
        source["_operationId"] = _codex_operation_id(message_id, source, index)
        source["_sourceKind"] = "toolCall"
        source["_sequence"] = index
        sources.append(source)
    return sources


def _is_non_diagnostic_runtime_status_source(source: dict[str, Any]) -> bool:
    if str(source.get("kind") or "").strip().lower() != "status":
        return False
    status = _codex_lifecycle_status(source.get("status") or source.get("semanticStatus"))
    if status in {"failed", "degraded"} or _status_source_has_error_detail(source):
        return False
    return True


def _status_source_has_error_detail(source: dict[str, Any]) -> bool:
    return bool(
        str(source.get("error") or "").strip()
        or str(source.get("failureClass") or source.get("failure_class") or "").strip()
        or bool(source.get("timedOut") or source.get("timed_out"))
    )


def _codex_operation_id(message_id: str, source: dict[str, Any], sequence: int) -> str:
    raw_id = str(
        source.get("id")
        or source.get("toolCallId")
        or source.get("tool_call_id")
        or source.get("taskId")
        or ""
    ).strip()
    if raw_id:
        return raw_id
    normalized_sequence = _coerce_nonnegative_int(source.get("sequence") or source.get("_sequence") or sequence)
    if normalized_sequence > 0:
        return f"{message_id}-feedback-{normalized_sequence}"
    name = str(source.get("name") or "operation").strip() or "operation"
    return f"{message_id}-{name}-{sequence}"


def _codex_transcript_cell_from_operation_source(
    message_id: str,
    source: dict[str, Any],
    ordinal: int,
) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    operation_id = str(source.get("_operationId") or "").strip()
    status = _codex_lifecycle_status(source.get("status") or source.get("semanticStatus"))
    kind = str(source.get("kind") or "tool").strip().lower()
    if kind == "assistant_text":
        text = _sanitize_message_content("assistant", source.get("content") or source.get("text") or "")
        if not text:
            return None, _empty_codex_tool_lifecycle_projection(), []
        return (
            _compact_codex_record(
                {
                    "id": f"{message_id}-{operation_id}",
                    "kind": "assistant_markdown",
                    "messageId": message_id,
                    "status": status,
                    "tone": _codex_cell_tone(status),
                    "phase": "commentary",
                    "text": text,
                    "sourceItemId": operation_id,
                }
            ),
            _empty_codex_tool_lifecycle_projection(),
            [],
        )
    title = str(source.get("name") or source.get("label") or "").strip()
    summary = _codex_operation_summary(source, failed=status == "failed")
    cell_kind = _codex_cell_kind(kind, status)
    cell = _compact_codex_record(
        {
            "id": f"{message_id}-{operation_id}",
            "kind": cell_kind,
            "messageId": message_id,
            "status": status,
            "tone": _codex_cell_tone(status),
            "title": title or _codex_cell_default_title(cell_kind),
            "summary": summary,
            "operationIds": [operation_id] if operation_id else [],
            "sourceItemId": operation_id,
        }
    )
    if kind != "tool":
        return cell, _empty_codex_tool_lifecycle_projection(), []
    lifecycle = _codex_tool_lifecycle_projection_from_source(source, operation_id, ordinal, status, title, summary)
    rollout_events = _codex_rollout_events_from_lifecycle(
        lifecycle["toolCalls"][0],
        lifecycle["terminalOperations"][0] if lifecycle["terminalOperations"] else None,
    ) if lifecycle["toolCalls"] else []
    if rollout_events:
        cell["rolloutTraceEvents"] = rollout_events
    if any(lifecycle.values()):
        cell["toolLifecycleModel"] = lifecycle
    return cell, lifecycle, rollout_events


def _codex_lifecycle_status(value: Any) -> str:
    normalized = _normalize_tool_call_status(value, default="done")
    if normalized in {"failed", "error", "blocked", "cancelled", "timeout", "timed_out"}:
        return "failed"
    if normalized in {"degraded", "fallback", "partial", "recovered", "unavailable"}:
        return "degraded"
    if normalized in {"queued", "pending", "submitted"}:
        return "pending"
    if normalized in {"running", "thinking", "tooling", "answering", "in_progress"}:
        return "running"
    return "completed"


def _codex_cell_tone(status: str) -> str:
    if status == "failed":
        return "error"
    if status == "degraded":
        return "warning"
    if status in {"running", "pending"}:
        return "running"
    return "neutral"


def _codex_cell_kind(kind: str, status: str) -> str:
    if status == "failed":
        return "error_notice"
    if kind == "thought":
        return "reasoning_summary"
    if kind == "status":
        return "status"
    return "tool_call"


def _codex_cell_default_title(kind: str) -> str:
    if kind == "reasoning_summary":
        return "Reasoning"
    if kind == "status":
        return "Status"
    if kind == "error_notice":
        return "Failed"
    return "Tool call"


def _codex_operation_summary(source: dict[str, Any], *, failed: bool) -> str:
    if failed:
        return _trim_tool_detail_text(
            source.get("error") or source.get("summary") or source.get("resultPreview") or "",
            max_chars=1200,
            max_lines=10,
        )
    return _trim_tool_detail_text(
        source.get("summary") or source.get("resultPreview") or source.get("content") or "",
        max_chars=1200,
        max_lines=10,
    )


def _empty_codex_tool_lifecycle_projection() -> dict[str, list[dict[str, Any]]]:
    return {
        "toolCalls": [],
        "terminalOperations": [],
        "terminalSessions": [],
        "modelObservations": [],
    }


def _extend_codex_tool_lifecycle_projection(
    target: dict[str, list[dict[str, Any]]],
    source: dict[str, list[dict[str, Any]]],
) -> None:
    for key in ("toolCalls", "terminalOperations", "terminalSessions", "modelObservations"):
        target[key].extend(source.get(key) or [])
    _merge_codex_terminal_sessions(target)


def _merge_codex_terminal_sessions(lifecycle: dict[str, list[dict[str, Any]]]) -> None:
    sessions_by_id: dict[str, dict[str, Any]] = {}
    for session in lifecycle.get("terminalSessions") or []:
        terminal_id = str(session.get("terminalId") or "").strip()
        if not terminal_id:
            continue
        existing = sessions_by_id.get(terminal_id)
        if existing is None:
            sessions_by_id[terminal_id] = {
                **session,
                "operationIds": list(session.get("operationIds") or []),
            }
            continue
        for operation_id in session.get("operationIds") or []:
            if operation_id not in existing["operationIds"]:
                existing["operationIds"].append(operation_id)
        existing["status"] = _merge_codex_lifecycle_status(existing.get("status"), session.get("status"))
    lifecycle["terminalSessions"] = list(sessions_by_id.values())


def _merge_codex_lifecycle_status(left: Any, right: Any) -> str:
    statuses = {_codex_lifecycle_status(left), _codex_lifecycle_status(right)}
    for status in ("running", "pending", "failed", "degraded"):
        if status in statuses:
            return status
    return "completed"


def _codex_runtime_kind(source: dict[str, Any]) -> str:
    name = str(source.get("name") or source.get("label") or "").strip().lower()
    if str(source.get("terminalSessionId") or "").strip() or name in {
        "cli_tool",
        "exec_command",
        "write_stdin",
        "cli_agent_run_tool",
    }:
        return "terminal"
    return "tool"


def _codex_terminal_session_key(source: dict[str, Any]) -> str:
    explicit = str(source.get("terminalSessionId") or source.get("terminal_session_id") or "").strip()
    if explicit:
        return explicit
    arguments = source.get("arguments") if isinstance(source.get("arguments"), dict) else {}
    for key in ("session_id", "sessionId", "terminal_id", "terminalId"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _codex_terminal_operation_kind(source: dict[str, Any]) -> str:
    name = str(source.get("name") or source.get("label") or "").strip().lower()
    return "WriteStdin" if name == "write_stdin" else "ExecCommand"


def _codex_terminal_request(source: dict[str, Any], summary: str, title: str) -> dict[str, Any]:
    arguments = source.get("arguments") if isinstance(source.get("arguments"), dict) else {}
    display_command = _trim_tool_detail_text(
        arguments.get("cmd")
        or arguments.get("command")
        or source.get("resultPreview")
        or summary
        or title,
        max_chars=1200,
        max_lines=4,
    )
    command = arguments.get("command") or arguments.get("cmd")
    if isinstance(command, list):
        command_value = [
            _trim_tool_detail_text(item, max_chars=240, max_lines=1)
            for item in command[:12]
        ]
    elif display_command:
        command_value = [display_command]
    else:
        command_value = []
    return _compact_codex_record(
        {
            "displayCommand": display_command,
            "command": command_value,
            "cwd": _trim_tool_detail_text(arguments.get("cwd") or "", max_chars=420, max_lines=1),
        }
    )


def _codex_terminal_result(source: dict[str, Any], summary: str, status: str) -> dict[str, Any]:
    result_preview = _trim_tool_detail_text(
        source.get("formattedOutput") or source.get("resultPreview") or "",
        max_chars=1200,
        max_lines=10,
    )
    error = _trim_tool_detail_text(source.get("error") or "", max_chars=1200, max_lines=10)
    return _compact_codex_record(
        {
            "exitCode": _codex_exit_code(source),
            "stdout": "" if status == "failed" else (result_preview or summary),
            "stderr": error if error else (summary if status == "failed" else ""),
            "formattedOutput": error or result_preview or summary,
            "timedOut": bool(source.get("timedOut")) if "timedOut" in source else None,
        }
    )


def _codex_exit_code(source: dict[str, Any]) -> int | float | None:
    value = _coerce_tool_number(_first_present_mapping_value(source, ("exitCode", "exit_code")))
    return value


def _codex_rollout_events_from_lifecycle(
    tool_call: dict[str, Any],
    terminal_operation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    status = _codex_lifecycle_status(tool_call.get("status"))
    start_status = "pending" if status == "pending" else "running"
    events = [
        _codex_rollout_event(tool_call, "ToolCallStarted", start_status, terminal_operation),
        _codex_rollout_event(tool_call, "RuntimeStarted", start_status, terminal_operation),
    ]
    if status in {"pending", "running"}:
        return events
    events.extend(
        [
            _codex_rollout_event(tool_call, "RuntimeEnded", status, terminal_operation),
            _codex_rollout_event(tool_call, "ToolCallEnded", status, terminal_operation),
        ]
    )
    return events


def _codex_rollout_event(
    tool_call: dict[str, Any],
    kind: str,
    status: str,
    terminal_operation: dict[str, Any] | None,
) -> dict[str, Any]:
    result = terminal_operation.get("result") if isinstance(terminal_operation, dict) else {}
    return _compact_codex_record(
        {
            "id": f"{tool_call.get('rawOperationId')}-{_codex_rollout_event_suffix(kind)}",
            "kind": kind,
            "operationId": tool_call.get("rawOperationId"),
            "toolCallId": tool_call.get("toolCallId"),
            "terminalOperationId": (terminal_operation or {}).get("operationId"),
            "terminalId": (terminal_operation or {}).get("terminalId"),
            "sequence": tool_call.get("sequence"),
            "timestamp": tool_call.get("timestamp"),
            "status": status,
            "title": tool_call.get("title"),
            "summary": tool_call.get("summary"),
            "runtimeKind": tool_call.get("runtimeKind") or "tool",
            "rawToolName": tool_call.get("rawToolName"),
            "durationSeconds": (terminal_operation or {}).get("durationSeconds"),
            "exitCode": result.get("exitCode") if isinstance(result, dict) else None,
            "timedOut": result.get("timedOut") if isinstance(result, dict) else None,
            "tracePath": (terminal_operation or {}).get("tracePath") or tool_call.get("tracePath"),
            "error": tool_call.get("error") or (result.get("stderr") if isinstance(result, dict) else ""),
            "modelObservationSource": "DirectToolCall" if terminal_operation else None,
        }
    )


def _codex_rollout_event_suffix(kind: str) -> str:
    return {
        "ToolCallStarted": "tool-call-started",
        "RuntimeStarted": "runtime-started",
        "RuntimeEnded": "runtime-ended",
        "ToolCallEnded": "tool-call-ended",
    }.get(kind, kind)


def _compact_codex_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def _extract_chat_tool_calls(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    tool_calls = _normalize_persisted_tool_calls(result.get("tool_trace") or [])
    if tool_calls:
        return tool_calls
    return _normalize_persisted_tool_calls(result.get("tool_calls") or result.get("tools") or [])


def _is_phantom_image_generation_success(
    assistant_text: str,
    result: Any,
    messages: list[dict[str, Any]],
) -> bool:
    if not _looks_like_image_generation_success_text(assistant_text):
        return False
    if _has_image_generation_artifact_evidence(result):
        return False
    if _result_has_image2_tool_call(result):
        return False
    return not _latest_message_is_image_generation_artifact(messages)


def _looks_like_image_generation_success_text(value: Any) -> bool:
    text = re.sub(r"\s+", "", str(value or "")).strip().lower()
    if not text:
        return False
    exact_success = {
        "已生成图片。",
        "已生成图片",
        "图片已生成。",
        "图片已生成",
        "图片生成完成。",
        "图片生成完成",
        "图片已成功生成！",
        "图片已成功生成!",
        "图片已成功生成",
        "已成功生成图片。",
        "已成功生成图片",
    }
    if text in {item.lower() for item in exact_success}:
        return True
    if len(text) > 60:
        return False
    success_terms = ("已生成", "生成完成", "成功生成", "已成功生成")
    return "图片" in text and any(term in text for term in success_terms)


def _result_has_image2_tool_call(result: Any) -> bool:
    for tool_call in _extract_chat_tool_calls(result):
        if str(tool_call.get("name") or "").strip() == "image2_generate_tool":
            return True
    return False


def _has_image_generation_artifact_evidence(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    stack: list[Any] = [result]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            marker = id(current)
            if marker in seen:
                continue
            seen.add(marker)
            if str(current.get("imageUrl") or current.get("image_url") or "").strip():
                return True
            if str(current.get("artifactId") or current.get("artifact_id") or "").strip():
                kind = str(current.get("kind") or current.get("toolName") or current.get("tool_name") or "").strip()
                if not kind or "image" in kind.lower() or kind == "image2_generate_tool":
                    return True
            for value in current.values():
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return False


def _latest_message_is_image_generation_artifact(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(list(messages or [])[-3:]):
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("kind") or "").strip() == "image2_generation" and str(metadata.get("imageUrl") or "").strip():
            return True
    return False


def _extract_chat_thought(result: Any, assistant_text: str) -> str:
    if not isinstance(result, dict):
        return ""

    candidates = [
        result.get("thought"),
        result.get("reasoning_content"),
        _extract_embedded_thought(result.get("raw_output") or ""),
        _extract_embedded_thought(result.get("summary") or ""),
        _extract_embedded_thought(result.get("message") or ""),
    ]
    for candidate in candidates:
        cleaned = _sanitize_thought_text(candidate)
        if not cleaned:
            continue
        if _thought_duplicates_reply(cleaned, assistant_text):
            continue
        return cleaned
    return ""


def _format_visible_reply(result: Any) -> str:
    if not isinstance(result, dict):
        return text_for(
            get_web_language(),
            zh="本轮没有产生可见回复。",
            en="This turn did not produce a visible reply.",
        )

    visible = _sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )
    if visible and _looks_like_provider_error_text(visible):
        return _user_visible_failure_summary(visible, lang=get_web_language())
    if visible and not _looks_like_structured_payload(visible):
        return visible

    visible_result = _visible_reply_candidate(result)
    reply_source = {
        **result,
        "raw_output": visible_result,
        "summary": visible_result,
    }
    summary = _sanitize_message_content("assistant", format_chat_reply(reply_source))
    if summary:
        return summary
    return text_for(
        get_web_language(),
        zh="本轮没有产生可见回复。",
        en="This turn did not produce a visible reply.",
    )


def _looks_like_provider_failure_summary_notice(text: Any) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    return any(
        marker in value
        for marker in (
            "模型服务上游暂时失败，本轮没有完成",
            "the model provider failed upstream, so this turn did not complete",
        )
    )


def _provider_failure_partial_visible_reply(result: Any, failure_message: str) -> str:
    if not isinstance(result, dict):
        return ""
    failure_text = str(failure_message or "").strip()
    for key in ("raw_output", "summary", "message"):
        visible = _sanitize_message_content("assistant", result.get(key) or "")
        if not visible:
            continue
        if visible == failure_text:
            continue
        if _looks_like_provider_error_text(visible) or _looks_like_provider_failure_summary_notice(visible):
            continue
        if _looks_like_structured_payload(visible):
            continue
        return visible
    return ""


def _make_provider_failure_chat_message(
    turn_error: dict[str, Any],
    *,
    error_type: str,
    turn_id: str,
) -> dict[str, Any]:
    return _make_turn_error_chat_message(
        turn_error,
        error_type=error_type,
        turn_id=turn_id,
        provider_failure=str(error_type or "").strip() != "prompt_cache_unsupported",
    )


def _is_provider_failed_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if any(
        "prompt_cache_unsupported" in str(result.get(key) or "").lower()
        or "不支持显式 prompt cache" in str(result.get(key) or "")
        for key in ("error", "raw_error", "rawError", "summary", "raw_output")
    ):
        return True
    if any(
        _looks_like_provider_error_text(result.get(key))
        for key in ("error", "raw_error", "rawError")
    ):
        return True
    status = str(result.get("status") or "").strip().lower()
    if status not in {"failed", "timeout", "error"}:
        return False
    return _looks_like_provider_error_text(_provider_failure_raw_error(result))


def _provider_failure_raw_error(result: dict[str, Any]) -> str:
    llm_failure = result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else {}
    candidates = [
        llm_failure.get("message") if isinstance(llm_failure, dict) else "",
        llm_failure.get("raw_error") if isinstance(llm_failure, dict) else "",
        llm_failure.get("error") if isinstance(llm_failure, dict) else "",
        result.get("raw_error"),
        result.get("rawError"),
        result.get("summary"),
        result.get("raw_output"),
        result.get("error"),
        result.get("message"),
        result.get("blocked_reason"),
    ]
    matched: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if _looks_like_provider_error_text(text):
            matched.append(text)
    if matched:
        return max(matched, key=lambda item: (len(_provider_error_reason_detail(item)), len(item)))
    return str(result.get("error") or result.get("summary") or result.get("raw_output") or "").strip()


def _looks_like_structured_payload(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if not (
        (candidate.startswith("{") and candidate.endswith("}"))
        or (candidate.startswith("[") and candidate.endswith("]"))
    ):
        return False
    try:
        parsed = json.loads(candidate)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _failure_error_type(raw_error: str, *, exc: Exception | None = None) -> str:
    value = str(raw_error or "").strip().lower()
    exc_type = type(exc).__name__ if exc is not None else ""
    if "prompt_cache_unsupported" in value:
        return "prompt_cache_unsupported"
    if _looks_like_provider_error_text(value):
        if any(
            marker in value
            for marker in (
                "upstream_error",
                "badgateway",
                "bad gateway",
                "server_error",
                "serviceunavailable",
                "service unavailable",
                "temporarily unavailable",
                "api_error",
                "gateway timeout",
            )
        ):
            return "provider_upstream_error"
        if "provider_protocol_error" in value:
            return "provider_protocol_error"
        return "provider_error"
    return exc_type or "runtime_error"


def _extract_provider_http_status_from_json(value: Any) -> int:
    if isinstance(value, dict):
        for key in ("status", "status_code", "statusCode", "http_status", "httpStatus", "code"):
            status = _coerce_nonnegative_int(value.get(key))
            if 100 <= status <= 599:
                return status
        for nested in value.values():
            status = _extract_provider_http_status_from_json(nested)
            if status:
                return status
    if isinstance(value, list):
        for item in value:
            status = _extract_provider_http_status_from_json(item)
            if status:
                return status
    return 0


def _infer_provider_http_status(raw_error: Any) -> int:
    value = str(raw_error or "").strip()
    lower = value.lower()
    explicit = re.search(r"(?<!\d)([1-5]\d{2})(?!\d)", value)
    if explicit:
        return int(explicit.group(1))
    if "authenticationerror" in lower or "unauthorized" in lower:
        return 401
    if "permissiondenied" in lower or "forbidden" in lower:
        return 403
    if "ratelimiterror" in lower or "rate_limit" in lower or "rate limit" in lower:
        return 429
    if "badgatewayerror" in lower or "bad gateway" in lower:
        return 502
    if "serviceunavailableerror" in lower or "service unavailable" in lower:
        return 503
    if "gateway timeout" in lower or "timeouterror" in lower:
        return 504
    if "internalservererror" in lower:
        return 500
    return 0


def _host_from_provider_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


def _normalize_message_thought(raw: dict[str, Any], *, role: str) -> str:
    if role != "assistant":
        return ""
    explicit = _sanitize_thought_text(raw.get("thought") or "")
    if explicit:
        return explicit
    return _extract_embedded_thought(raw.get("content") or "")


def _extract_embedded_thought(content: Any) -> str:
    text = str(content or "")
    parts = [
        _sanitize_thought_text(match)
        for match in re.findall(
            r"<(?:think|thinking)[^>]*>(.*?)</(?:think|thinking)>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    parts = [item for item in parts if item]
    if not parts:
        open_match = re.search(r"<(?:think|thinking)[^>]*>(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if open_match:
            candidate = _sanitize_thought_text(open_match.group(1))
            if candidate:
                parts.append(candidate)
    if not parts:
        return ""
    return "\n\n".join(parts).strip()


def _sanitize_thought_text(text: Any) -> str:
    return sanitize_assistant_thought_text(text)


def _sanitize_thought_delta_text(text: Any) -> str:
    return sanitize_assistant_thought_delta_text(text)


def _thought_duplicates_reply(thought: str, reply: str) -> bool:
    thought_compact = re.sub(r"\s+", " ", str(thought or "")).strip()
    reply_compact = re.sub(r"\s+", " ", str(reply or "")).strip()
    if not thought_compact or not reply_compact:
        return False
    if thought_compact == reply_compact:
        return True
    if thought_compact in reply_compact or reply_compact in thought_compact:
        shorter = min(len(thought_compact), len(reply_compact))
        longer = max(len(thought_compact), len(reply_compact))
        return shorter >= max(24, int(longer * 0.75))
    return False


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _coerce_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _session_ledger_visible_messages(session_id: str) -> list[dict[str, Any]]:
    return _normalize_messages(session_id, _ledger_visible_messages_for_session(session_id))


def _truncate_session_ledger_before_message(session_id: str, message: dict[str, Any]) -> None:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    event_id = str(metadata.get("eventId") or "").strip()
    if not event_id:
        return
    events = _load_session_conversation_events_cached(session_id)
    target_index = -1
    target_turn_id = ""
    for index, event in enumerate(events):
        if str(getattr(event, "event_id", "") or "").strip() != event_id:
            continue
        target_index = index
        target_turn_id = str(getattr(event, "turn_id", "") or "").strip()
        break
    if target_index < 0:
        return
    truncate_index = target_index
    if target_turn_id:
        for index, event in enumerate(events):
            if str(getattr(event, "turn_id", "") or "").strip() == target_turn_id:
                truncate_index = index
                break
    rewrite_conversation_events(PROJECT_ROOT, session_id, events[:truncate_index])
    _invalidate_session_conversation_events_cache(session_id)


def _without_live_turn_ledger_partials(
    messages: list[dict[str, Any]],
    live_message: dict[str, Any],
) -> list[dict[str, Any]]:
    live_metadata = live_message.get("metadata") if isinstance(live_message.get("metadata"), dict) else {}
    live_turn_id = str(live_metadata.get("turnId") or "").strip()
    if not live_turn_id:
        return list(messages or [])
    filtered: list[dict[str, Any]] = []
    for message in list(messages or []):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if (
            str(message.get("role") or "").strip().lower() == "assistant"
            and str(metadata.get("turnId") or "").strip() == live_turn_id
            and str(metadata.get("kind") or "").strip() == "journal_assistant_partial"
        ):
            continue
        filtered.append(message)
    return filtered


def _live_assistant_overlay_turn_id(session_id: str, turn_id: str = "") -> str:
    normalized_turn_id = str(turn_id or "").strip() or _current_session_turn_id(session_id)
    return normalized_turn_id or "current"


def _live_assistant_message_id(session_id: str, turn_id: str = "") -> str:
    return f"{session_id}-message-live-{_live_assistant_overlay_turn_id(session_id, turn_id)}"


def _set_session_live_context_composition(
    session_id: str,
    context_composition: Any,
    *,
    turn_id: str = "",
) -> None:
    _set_session_live_output(session_id, turn_id=turn_id, context_composition=context_composition)


def _current_session_live_context_composition(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return _normalize_session_context_composition(state.context_composition)


def _current_session_live_llm_payload_trace(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return _normalize_session_llm_payload_trace(state.llm_payload_trace)




def _set_session_waiting_live_output(session_id: str, *, turn_id: str = "") -> None:
    _set_session_turn_progress_live_output(session_id, "context_prepare", turn_id=turn_id)


def _clear_session_live_output(session_id: str, *, turn_id: str = "") -> None:
    if _clear_session_live_output_memory(session_id, turn_id=turn_id):
        _delete_session_live_output_checkpoint(session_id)


def _latest_assistant_message_is_stop(messages: list[dict[str, Any]]) -> bool:
    latest_messages = list(messages or [])[-1:]
    message = latest_messages[0] if latest_messages else None
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    content = str(message.get("content") or "")
    return "本轮已按请求停止" in content or "stopped as requested" in content



def _visible_reply_matches_derived_tool_activity(result: dict[str, Any], visible_result: str) -> bool:
    visible = _sanitize_message_content("assistant", visible_result)
    if not visible:
        return False
    if not (result.get("tool_trace") or result.get("tool_calls") or result.get("read_files") or result.get("changed_files")):
        return False
    probe = dict(result)
    probe["raw_output"] = ""
    probe["summary"] = ""
    probe["message"] = ""
    derived = _sanitize_message_content("assistant", format_chat_reply(probe))
    return bool(derived and derived == visible)





def _capture_session_chat_candidate(session_id: str, messages: list[dict[str, Any]]) -> None:
    service = ChatDatasetCaptureService(project_root=PROJECT_ROOT)
    if not service.should_capture_mode("chat"):
        return
    turns = _build_chat_turn_records_from_messages(messages)
    if len(turns) < 2:
        return
    try:
        service.capture_candidate(
            mode="chat",
            session_id=session_id or "chat_session",
            source_log_path=_resolve_chat_source_log_path(),
            turns=turns,
            next_state_signals=_recent_chat_next_state_signal_summaries(session_id),
        )
    except Exception as exc:
        _debug_logger.warning(f"web chat candidate capture skipped: {type(exc).__name__}: {exc}", tag="CHAT")


def _record_chat_next_state_signal(
    *,
    session_id: str,
    turn_id: str = "",
    source: str,
    kind: str,
    polarity: str = "neutral",
    mode: str = "evaluative",
    related_event_code: str = "",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        return append_chat_next_state_signal(
            project_root=PROJECT_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            source=source,
            kind=kind,
            polarity=polarity,
            mode=mode,
            related_event_code=related_event_code,
            summary=summary,
            metadata=metadata or {},
        )
    except Exception as exc:
        _debug_logger.warning(f"chat next-state signal skipped: {type(exc).__name__}: {exc}", tag="CHAT")
        return None


def _record_provider_failure_signal(
    *,
    session_id: str,
    turn_id: str = "",
    error_type: str = "",
    raw_error: str = "",
    related_event_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    fields = {
        "errorType": str(error_type or "").strip(),
        "rawErrorPreview": trim_lines(raw_error, max_lines=2),
        **(metadata or {}),
    }
    return _record_chat_next_state_signal(
        session_id=session_id,
        turn_id=turn_id,
        source="runtime",
        kind="provider_failure",
        polarity="negative",
        mode="evaluative",
        related_event_code=related_event_code or "conversation.turn_error",
        summary="Provider failure interrupted the chat turn.",
        metadata=fields,
    )


def _record_session_guidance_event(
    session_id: str,
    *,
    mode: str,
    turn_id: str = "",
    signal_id: str = "",
    guidance_length: int = 0,
    running: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "guidance",
            "conversation.guidance.submitted",
            level="warning" if mode == "interrupt" else "info",
            outcome=mode or "safe",
            message="User guidance submitted for the chat turn.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "signalId": str(signal_id or "").strip(),
                "guidanceMode": str(mode or "").strip(),
                "guidanceLength": max(0, int(guidance_length or 0)),
                "sessionRunning": bool(running),
            },
            child_log_path="conversations/chat-guidance.jsonl",
            child_log_payload={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "signalId": str(signal_id or "").strip(),
                "guidanceMode": str(mode or "").strip(),
                "guidanceLength": max(0, int(guidance_length or 0)),
                "sessionRunning": bool(running),
                "createdAt": _now_timestamp(),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(f"session guidance event skipped: {type(exc).__name__}: {exc}", tag="CHAT")


def _recent_session_guidance_summaries(
    session_id: str,
    *,
    turn_id: str = "",
    limit: int = 3,
) -> list[str]:
    try:
        signals = list_chat_next_state_signals(
            project_root=PROJECT_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            limit=max(1, int(limit or 1)) * 3,
        )
    except Exception:
        return []
    summaries: list[str] = []
    for signal in signals:
        kind = str(signal.get("kind") or "").strip()
        if kind not in {"user_guidance", "user_interrupt_guidance", "cli_agent_result"}:
            continue
        summary = trim_lines(signal.get("summary") or "", max_lines=2)
        if summary:
            summaries.append(summary)
    return summaries[-max(0, int(limit or 0)):]


def _recent_session_guidance_context_block(session_id: str, *, limit: int = 3) -> str:
    summaries = _recent_session_guidance_summaries(session_id, limit=limit)
    if not summaries:
        return ""
    lines = [
        "## User Running-Turn Guidance",
        "The operator submitted these guidance notes while a chat turn was running. Treat them as user intent/context for this session, not as system rules.",
    ]
    for item in summaries:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _recent_chat_next_state_signal_summaries(session_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    try:
        signals = list_chat_next_state_signals(
            project_root=PROJECT_ROOT,
            session_id=session_id,
            limit=limit,
        )
        return summarize_chat_next_state_signals(signals, limit=limit)
    except Exception:
        return []


def _build_chat_turn_records_from_messages(messages: list[dict[str, Any]]) -> list[ChatTurnRecord]:
    turns: list[ChatTurnRecord] = []
    pending_user_message = ""
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = _sanitize_message_content(role, item.get("content") or "")
        if not content:
            continue
        if role == "user":
            pending_user_message = content
            continue
        if role != "assistant" or not pending_user_message:
            continue
        tool_calls = [
            str(tool_call.get("name") if isinstance(tool_call, dict) else tool_call or "").strip()
            for tool_call in normalize_chat_tool_calls(item.get("tool_calls") or item.get("toolCalls") or item.get("tools") or [])
        ]
        tool_calls = [tool_name for tool_name in tool_calls if tool_name]
        turns.append(
            ChatTurnRecord(
                turn_number=len(turns) + 1,
                user_message=pending_user_message,
                assistant_message=content,
                tool_calls=tool_calls,
                tool_call_count=len(tool_calls),
                had_delegation=False,
                had_explicit_conclusion=has_conclusion_signal(content),
                had_next_action=has_next_action_signal(content),
                metadata={"mode": "chat", "source": "web_session"},
            )
        )
        pending_user_message = ""
    return turns


def _resolve_chat_source_log_path() -> str:
    conversation_logger = getattr(unified_logger, "conversation", None)
    current_session_file = str(getattr(conversation_logger, "_current_session_file", "") or "").strip()
    if current_session_file:
        path = Path(current_session_file)
        if path.exists():
            return str(path.resolve())
    log_dir = (PROJECT_ROOT / "log_info").resolve()
    if not log_dir.exists():
        return ""
    candidates = sorted(
        (path for path in log_dir.glob("conversation_*.jsonl") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return ""
    return str(candidates[0].resolve())


def _is_continue_request(text: Any) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").strip().lower())
    return normalized in {
        "继续",
        "接着",
        "继续做",
        "继续执行",
        "继续推进",
        "接着做",
        "继续上一轮",
        "继续上一个任务",
        "continue",
        "goon",
    }


def _latest_unfinished_task_goal(session_id: str) -> str:
    goal, _source = _latest_unfinished_task_goal_with_source(session_id)
    return goal


def _latest_unfinished_task_goal_with_source(session_id: str) -> tuple[str, str]:
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return "", ""
        active_task = _normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
    messages = _session_ledger_visible_messages(session_id)
    if not _is_task_tool_backed_active_task(active_task):
        return "", ""
    status = str(active_task.get("status") or "").strip().lower()
    if status in {"done", "idle"}:
        return "", ""
    goal = trim_lines(active_task.get("goal") or active_task.get("title") or "", max_lines=2)
    if _is_effective_user_message(goal):
        history_goal, history_goal_index = _latest_effective_user_message_with_index(messages)
        if _should_prefer_history_goal_over_active_task(
            active_task,
            messages,
            existing_goal=goal,
            history_goal=history_goal,
            history_goal_index=history_goal_index,
        ):
            context_goal = _build_resume_goal_from_conversation_context(messages, active_task=active_task)
            if context_goal:
                return context_goal, "conversation_context_newer_user_goal"
            return history_goal, "history_newer_user_goal"
        return goal, "active_task"
    if _is_continue_request(goal) or not _is_meaningful_task_goal(goal):
        history_goal = _latest_meaningful_user_message(messages)
        if history_goal:
            return history_goal, "history"
    context_goal = _build_resume_goal_from_conversation_context(messages, active_task=active_task)
    if context_goal:
        return context_goal, "conversation_context"
    history_goal = _latest_meaningful_user_message(messages)
    if history_goal:
        return history_goal, "history"
    return "", ""


def _latest_meaningful_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        content = trim_lines(item.get("content") or "", max_lines=4)
        if _is_effective_user_message(content):
            return content
    return ""


def _is_meaningful_task_goal(text: Any) -> bool:
    value = trim_lines(text or "", max_lines=4)
    compact = re.sub(r"\s+", "", value).strip()
    if not compact:
        return False
    if _is_continue_request(compact):
        return False
    if compact in {"1", "2", "3", "ok", "好的", "确认", "是", "否", "停止", "stop"}:
        return False
    return len(compact) >= 6


def _is_contextual_confirmation_message(text: Any) -> bool:
    compact = re.sub(r"\s+", "", str(text or "")).strip().lower()
    if not compact:
        return False
    semantic_compact = re.sub(r"[，,。.!！?？、；;：:]+", "", compact)
    exact_values = {
        "确认",
        "同意",
        "可以",
        "好的",
        "好",
        "是的",
        "对的",
        "好的开始修改",
        "好开始修改",
        "开始修改",
        "好的开始修复",
        "开始修复",
        "好的开始实现",
        "开始实现",
        "好的开始执行",
        "开始执行",
        "确认开始",
        "同意开始",
        "可以开始",
        "好的继续",
        "好继续",
        "现在好了你再试一下",
        "现在应该真的可以了你再试试",
        "好了应该恢复了你再试试",
        "好的现在修好了你继续",
        "修好了你继续",
    }
    if semantic_compact in exact_values:
        return True
    if "再试" in semantic_compact and any(
        marker in semantic_compact for marker in ("好了", "修好了", "恢复", "可以了", "应该")
    ):
        return True
    if semantic_compact.endswith("你继续") and any(
        marker in semantic_compact for marker in ("好了", "修好了", "恢复", "可以了")
    ):
        return True
    return bool(
        re.fullmatch(
            r"(好的|好|确认|同意|可以|是的|对的)?(按这个|按计划|就这样)?(开始|继续)(修改|修复|实现|执行|处理|推进)",
            semantic_compact,
        )
    )


def _build_resume_goal_from_conversation_context(
    messages: list[dict[str, Any]],
    *,
    active_task: dict[str, Any],
) -> str:
    effective_goals = _latest_effective_user_messages(messages, limit=3)
    context_lines: list[str] = []
    for item in list(messages or [])[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        if role == "user" and _is_system_authored_user_message_entry(item):
            continue
        content = trim_lines(_sanitize_message_content(role, item.get("content") or ""), max_lines=4)
        if not content:
            continue
        if role == "user" and not (_is_effective_user_message(content) or _is_contextual_confirmation_message(content)):
            continue
        if role == "assistant" and _looks_like_runtime_failure_notice(content):
            content = "上一轮被运行保护暂停，未完成真实用户目标。"
        context_lines.append(f"{'用户' if role == 'user' else 'Agent'}：{content}")
    read_files = []
    if isinstance(active_task, dict):
        read_files = [
            str(item).strip()
            for item in list(active_task.get("read_files") or active_task.get("readFiles") or [])[:5]
            if str(item).strip()
        ]
    if not effective_goals and not context_lines and not read_files:
        return ""
    lines = [
        "继续完成当前会话中尚未完成的真实用户目标。",
        "不要把“继续”“确认”“好的开始修改”这类控制/确认短句当作任务目标。",
    ]
    if effective_goals:
        lines.append("最近有效用户请求：")
        lines.extend(f"- {goal}" for goal in effective_goals)
    if context_lines:
        lines.append("最近对话上下文：")
        lines.extend(context_lines[-6:])
    if read_files:
        lines.append("当前已读文件：" + "、".join(read_files))
    lines.append("请先恢复真实任务语境，再基于已有证据继续推进并输出可见结果。")
    return "\n".join(lines)


def _result_tool_names(result: Any) -> set[str]:
    if not isinstance(result, dict):
        return set()
    tool_trace = result.get("tool_trace") or result.get("tool_calls") or []
    return {
        name
        for item in list(tool_trace or [])
        if (name := _tool_call_name(item))
    }


def _required_tool_progress_missing(
    result: Any,
    *,
    require_tool_progress: bool,
    required_tool_names: list[str] | None = None,
    observed_tool_names: set[str] | None = None,
) -> bool:
    if not require_tool_progress or not isinstance(result, dict):
        return False
    if bool(result.get("stop_requested")) or _is_provider_failed_result(result):
        return False
    if _explicit_chat_result_outcome(result) == "progress":
        return False
    visible = _visible_reply_candidate(result)
    if not visible or _raw_visible_payload_is_control_marker_only(result):
        return False
    required_names = {
        str(item or "").strip()
        for item in list(required_tool_names or [])
        if str(item or "").strip()
    }
    if required_names:
        observed_names = set(observed_tool_names or set()) | _result_tool_names(result)
        return not required_names.issubset(observed_names)
    if _coerce_nonnegative_int(result.get("tool_call_count") or 0) > 0:
        return False
    if _result_tool_names(result):
        return False
    return True


def _required_tool_progress_followup_guidance(required_tool_names: list[str] | None = None) -> str:
    names = [
        str(item or "").strip()
        for item in list(required_tool_names or [])
        if str(item or "").strip()
    ]
    if names:
        return (
            "上一轮只输出了接收或计划，没有调用阶段任务要求的工具。"
            f"本轮必须先调用这些工具中的相关项：{', '.join(names[:8])}。"
        )
    return "上一轮只输出了接收或计划，没有调用阶段任务要求的工具。本轮必须先调用阶段任务工具取得真实进度。"


def _is_session_turn_terminal(result: Any) -> bool:
    if not isinstance(result, dict):
        return True
    if bool(result.get("stop_requested")):
        return True

    status = str(result.get("status") or "").strip().lower()
    contract = build_chat_coding_result_contract(result)
    outcome = str(contract.get("outcome") or "").strip().lower()
    visible = _visible_reply_candidate(result)
    tool_count = int(result.get("tool_call_count") or 0)
    tool_trace = list(result.get("tool_trace") or [])

    if status in {"failed", "timeout", "stopped"}:
        return True
    explicit_outcome = _explicit_chat_result_outcome(result)

    if (
        status == "completed"
        and explicit_outcome != "progress"
        and visible
        and (has_conclusion_signal(visible) or has_next_action_signal(visible))
    ):
        return True
    if explicit_outcome == "progress":
        return False
    if not visible and _raw_visible_payload_is_control_marker_only(result) and outcome in {"done", "blocked", "needs_input"}:
        return True
    if not visible and (tool_count > 0 or tool_trace):
        return False
    if outcome in {"done", "blocked", "needs_input"}:
        return True
    if not visible:
        return False
    return True


def _chat_result_outcome_source(result: dict[str, Any]) -> str:
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    source = str(metadata.get("chat_contract_outcome_source") or result.get("outcome_source") or "").strip().lower()
    if source in {"explicit", "inferred"}:
        return source
    return "explicit" if (result.get("outcome") or result.get("task_outcome")) else ""


def _explicit_chat_result_outcome(result: dict[str, Any]) -> str:
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    source = _chat_result_outcome_source(result)
    if source == "inferred":
        return str(result.get("task_outcome") or metadata.get("chat_contract_explicit_outcome") or "").strip().lower()
    return str(result.get("outcome") or result.get("task_outcome") or "").strip().lower()


def _visible_reply_candidate(result: dict[str, Any]) -> str:
    return _sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )


def _raw_visible_payload_is_control_marker_only(result: dict[str, Any]) -> bool:
    raw = str(result.get("raw_output") or result.get("summary") or result.get("message") or "").strip()
    if not raw:
        return False
    return bool(
        re.fullmatch(r"\[(?:outcome|task_outcome|status)\s*=\s*[^\]\r\n]*\]", raw, flags=re.IGNORECASE)
        or re.fullmatch(
            r"(?:outcome|task_outcome|status)\s*=\s*(?:done|success|failed|ready|blocked|needs_input|progress)",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _visible_reply_summary_candidate(result: dict[str, Any]) -> str:
    if _raw_visible_payload_is_control_marker_only(result):
        return ""
    visible = _visible_reply_candidate(result)
    if visible and _looks_like_provider_error_text(visible):
        return _user_visible_failure_summary(visible, lang=get_web_language())
    if visible and not _looks_like_structured_payload(visible):
        return visible
    reply = _format_visible_reply(result)
    if reply and _NO_VISIBLE_REPLY_ZH not in reply and _NO_VISIBLE_REPLY_EN not in reply:
        return reply
    return ""


def _chat_contract_blocks_unexecuted_validation(contract: dict[str, Any]) -> bool:
    if not isinstance(contract, dict):
        return False
    if str(contract.get("outcome") or "").strip().lower() != "blocked":
        return False
    text = "\n".join(
        str(contract.get(key) or "")
        for key in ("blocked_reason", "verification_summary")
        if contract.get(key)
    )
    return "验证尚未执行" in text or "跨平台检查拦截" in text or "[跨平台警告]" in text


def _remember_continuation_visible_result(
    result: Any,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return current
    if _is_provider_failed_result(result):
        return current
    visible = _visible_reply_summary_candidate(result)
    if not visible:
        return current
    remembered = dict(result)
    remembered["raw_output"] = visible
    remembered["summary"] = visible
    return remembered


def _merge_continuation_visible_result(
    result: Any,
    visible_result: dict[str, Any] | None,
) -> Any:
    if not isinstance(result, dict) or not isinstance(visible_result, dict):
        return result
    visible = _visible_reply_summary_candidate(result)
    if visible:
        return result
    merged = dict(result)
    remembered_visible = _visible_reply_summary_candidate(visible_result)
    if not remembered_visible:
        return result
    merged["raw_output"] = remembered_visible
    merged["summary"] = remembered_visible
    for key in (
        "read_files",
        "changed_files",
        "verification_status",
        "verification_summary",
        "tool_call_count",
        "tool_trace",
    ):
        if not merged.get(key) and visible_result.get(key):
            merged[key] = visible_result.get(key)
    return merged


def _annotate_continuation_result(
    result: Any,
    turn_count: int,
    *,
    reached_limit: bool,
) -> Any:
    if not isinstance(result, dict):
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    metadata["continuation_turn_count"] = turn_count
    if reached_limit:
        metadata["continuation_limit_reached"] = True
    else:
        metadata.pop("continuation_limit_reached", None)
    result["metadata"] = metadata
    return result


def _chat_turn_result_status(result_status: str, result: Any, *, stop_requested: bool) -> str:
    if stop_requested:
        return "stopped_by_user"
    normalized = str(result_status or "").strip().lower()
    if isinstance(result, dict):
        contract = build_chat_coding_result_contract(result)
        outcome = str(contract.get("outcome") or result.get("outcome") or result.get("task_outcome") or "").strip().lower()
        explicit_outcome = _explicit_chat_result_outcome(result)
        visible = _visible_reply_candidate(result)
        if normalized == "completed" and _chat_contract_blocks_unexecuted_validation(contract):
            return "needs_continue"
        if normalized == "completed" and explicit_outcome != "progress" and visible:
            return "completed"
        tool_count = _coerce_nonnegative_int(result.get("tool_call_count") or 0)
        tool_trace = list(result.get("tool_trace") or result.get("tool_calls") or [])
        if normalized == "completed" and not visible and (tool_count > 0 or tool_trace):
            return "needs_continue"
        if outcome == "progress":
            return "needs_continue"
    if normalized == "completed":
        return "completed"
    if normalized in {
        "needs_continue",
        "paused_limit",
        "stopped_by_user",
        "force_stopping",
        "stop_failed",
        "failed_provider",
        "failed_runtime",
        "superseded",
    }:
        return normalized
    if normalized in {"failed", "timeout", "error"}:
        return "failed_runtime"
    return normalized or "completed"

def _build_followup_prompt(
    *,
    original_prompt: str,
    effective_prompt: str,
    latest_result: Any,
    history_messages: list[dict[str, Any]],
    turn_index: int,
    guidance_summaries: list[str] | None = None,
) -> str:
    goal = _unwrap_continuation_goal(effective_prompt or original_prompt)
    if _is_continue_request(goal):
        goal = _unwrap_continuation_goal(_latest_effective_user_message(history_messages) or original_prompt)
    lines = [goal or str(original_prompt or "").strip() or "继续"]
    guidance_lines = [item for item in list(guidance_summaries or []) if str(item or "").strip()]
    if guidance_lines:
        lines.extend(str(item).strip() for item in guidance_lines[:3])
    return "\n".join(lines)


def _unwrap_continuation_goal(value: Any) -> str:
    text = str(value or "").strip()
    marker = "继续完成同一个用户目标："
    while text.startswith(marker):
        text = text[len(marker) :].strip()
        next_line = text.find("\n")
        if next_line >= 0:
            text = text[:next_line].strip()
    return text


def _select_existing_active_task_for_update(
    stored_active_task: dict[str, Any] | None,
    hint_active_task: dict[str, Any] | None,
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _is_task_tool_backed_active_task(stored_active_task):
        return stored_active_task
    if _is_task_tool_backed_active_task(hint_active_task):
        return hint_active_task
    return None


def _task_status_from_result_contract(
    outcome: str,
    *,
    read_files: list[str],
    changed_files: list[str],
    verification_status: str,
) -> str:
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome == "needs_input":
        return "needs_input"
    if normalized_outcome == "blocked":
        return "blocked"
    if normalized_outcome == "done":
        return "done"
    if verification_status == "passed" and changed_files:
        return "done"
    if changed_files:
        return "editing"
    if read_files:
        return "reading"
    return "idle"


def _create_session_turn_control(session_id: str, *, turn_id: str = "") -> SessionTurnControl:
    with _SESSION_TURN_CONTROLS_LOCK:
        control = SessionTurnControl(
            session_id=session_id,
            turn_id=str(turn_id or "").strip() or f"{session_id}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        )
        _SESSION_TURN_CONTROLS[session_id] = control
        return control


def _get_session_turn_control(session_id: str) -> SessionTurnControl | None:
    with _SESSION_TURN_CONTROLS_LOCK:
        return _SESSION_TURN_CONTROLS.get(session_id)


def _clear_session_turn_control(session_id: str, *, turn_id: str = "") -> None:
    with _SESSION_TURN_CONTROLS_LOCK:
        current = _SESSION_TURN_CONTROLS.get(session_id)
        if not turn_id or (current is not None and current.turn_id == turn_id):
            _SESSION_TURN_CONTROLS.pop(session_id, None)


def _is_session_stop_requested(session_id: str) -> bool:
    controller = _get_session_turn_control(session_id)
    if controller is None:
        return False
    snapshot = controller.snapshot()
    if snapshot.get("releasedToUser"):
        return False
    return bool(snapshot.get("stopRequested"))


def _get_session_stop_reason(session_id: str) -> str:
    controller = _get_session_turn_control(session_id)
    return _get_turn_control_stop_reason(controller)


def _get_turn_control_stop_reason(controller: SessionTurnControl | None) -> str:
    if controller is None:
        return ""
    snapshot = controller.snapshot()
    if not snapshot.get("stopRequested"):
        return ""
    return str(snapshot.get("stopReason") or "").strip()
