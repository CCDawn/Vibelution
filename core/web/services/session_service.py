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
from config.settings import get_config, get_web_chat_config
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
    conversation_ledger_workspace_root,
    conversation_visible_messages_from_events,
    conversation_turn_items_from_events,
    latest_ledger_sequence,
    latest_open_turn_id,
    load_conversation_events,
    load_conversation_preview_slice,
    rewrite_conversation_events,
)
from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED
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
from core.logging import debug as _debug_logger
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
    load_active_conversation_id,
    load_session_chat_state,
    list_session_runtime_ids,
    normalize_chat_attachments,
    normalize_chat_messages,
    normalize_chat_tool_calls,
    save_chat_state,
    save_session_chat_state,
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
    supervised_role_runtime_tools,
    update_agent_instance,
)
from .runtime_scene_service import record_runtime_scene_conversation_event, record_runtime_scene_event
from .session.list_cache import (
    SESSION_LIST_CACHE_TTL_SECONDS as _SESSION_LIST_CACHE_TTL_SECONDS,
    _SESSION_LIST_CACHE,
    _SESSION_LIST_CACHE_CONDITION,
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
from .session.proactive import (
    cancel_agent_plugin_proactive_turns,
    cancel_proactive_turn_context,
    release_proactive_turn_context,
    submit_session_proactive_turn,
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
    reserve_session_execution_slot,
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
    _append_session_reasoning_item_if_needed,
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
    _append_missing_canonical_result_items,
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
    reset_all_agent_test_conversations,
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
from core.web.services.session.session_bulk_delete import (
    MAX_BULK_SESSION_IDS,
    bulk_delete_chat_sessions,
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
    _ensure_session_conversation_record,
    _session_has_openable_body,
    _retire_unopenable_directory_session,
    _recover_agent_id_from_session_journal,
    _recover_stage_task_workspace_conversation,
    _recover_missing_conversation_from_workspace_locked,
    _session_workspace_dir_if_present,
    _is_session_workspace_intentionally_deleted,
    _mark_session_workspace_intentionally_deleted,
    _session_deleted_marker_path,
    _session_workspace_has_recoverable_activity,
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
    _assistant_timeline_covers_final_content,
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
    _enqueue_direct_session_submit_kernel_trace,
    _await_last_submit_kernel_trace,
    _record_direct_session_submit_kernel_trace_event,
    _active_chat_turn_work_run_id_for_session,
    _release_stale_chat_turn_work_run,
    reconcile_stale_chat_turn_work_runs,
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
from core.web.services.session.events import (
    _record_session_cycle_message,
    _record_session_delete_event,
    _record_session_execution_registry_event,
    _record_session_guidance_event,
    _record_session_catalog_read_event,
    _record_session_catalog_shadow_query_event,
    _record_session_list_loaded_event,
    _record_session_list_prewarm_event,
    _record_session_list_query_event,
    _record_session_message_edit_resubmit_event,
    _record_session_message_edit_resubmit_rejected_event,
    _record_session_message_encoding_rejected,
    _record_session_skill_command_event,
    _record_session_turn_accepted_event,
    _record_session_turn_lifecycle_event,
    _record_session_turn_result_log,
    _record_session_turn_scheduled_event,
    _record_session_turn_started_event,
    _record_session_turn_subpackage_event,
    _record_session_turn_trace_event,
    _record_session_turn_visible_message,
    _record_session_user_message_filtered_event,
)
from core.web.services.session.session_ops import (
    _build_chat_turn_records_from_messages,
    _build_contextual_confirmation_prompt,
    _build_resume_goal_from_conversation_context,
    _build_terminal_error_turn_item,
    _chat_turn_result_status,
    _codex_transcript_cell_from_operation_source,
    _codex_transcript_operation_sources,
    _is_contextual_confirmation_message,
    _is_session_turn_terminal,
    _latest_unfinished_task_goal,
    _latest_unfinished_task_goal_with_source,
    _load_conversation_detail_target,
    _make_chat_message,
    _make_local_runtime_error_chat_message,
    _persist_dirty_session_runtime_rows,
    _pending_tool_governance_requests_for_session,
    _terminal_reason_for_turn,
    _terminal_reason_from_conversation,
    _remove_replacement_direct_session_after_failed_agent_reset,
    _repair_child_root_agent_direct_session_bindings,
    _repair_stale_running_conversation,
    _repair_stale_running_conversations,
    _session_fixed_model_choice,
    _session_prompt_cache_partition,
    _session_query_matches,
    _session_turn_item_from_codex_cell,
    _source_collection_stage_task_continuation_metadata,
    _source_collection_stage_task_continuation_prompt,
    _supersede_active_session_turn_for_edit,
    _terminal_error_turn_item,
    append_session_assistant_artifact_message,
    prewarm_session_list_cache,
    update_chat_session,
    update_chat_session_title,
    update_session_reasoning_effort,
)
from core.web.services.session.signals_format import (
    _active_task_content_preview,
    _annotate_continuation_result,
    _attach_session_prompt_cache_metadata,
    _build_followup_prompt,
    _build_message_timeline_items,
    _cache_average_from_usage,
    _capture_session_chat_candidate,
    _compact_preview_text,
    _compact_tool_loop_failure_hint,
    _copy_tool_result_fact_fields,
    _current_session_live_llm_payload_trace,
    _dedupe_turn_error_messages,
    _ensure_assistant_visible_text,
    _extract_chat_thought,
    _extract_embedded_thought,
    _extract_provider_http_status_from_json,
    _failure_error_type,
    _find_turn_scoped_assistant_message,
    _format_visible_reply,
    _has_image_generation_artifact_evidence,
    _history_message_turn_id,
    _history_messages_for_agent_seed,
    _host_from_provider_url,
    _image_context_prompt_for_retry,
    _image_context_request_for_retry,
    _image_context_request_from_user_message,
    _infer_provider_http_status,
    _is_phantom_image_generation_success,
    _is_provider_failed_result,
    _latest_effective_user_message,
    _latest_effective_user_message_with_index,
    _latest_effective_user_messages,
    _latest_message_is_image_generation_artifact,
    _lightweight_chat_payload_decision,
    _looks_like_image_generation_success_text,
    _looks_like_image_retry_context,
    _looks_like_provider_failure_summary_notice,
    _looks_like_runtime_failure_notice,
    _looks_like_tool_unavailable_claim,
    _make_provider_failure_chat_message,
    _merge_continuation_visible_result,
    _message_list_chars,
    _message_list_content_preview,
    _normalize_latest_preview_messages,
    _normalize_llm_payload_trace_counts,
    _normalize_llm_payload_trace_map,
    _normalize_optional_bool,
    _not_called_cache_composition,
    _provider_failure_partial_visible_reply,
    _provider_failure_raw_error,
    _raw_visible_payload_is_control_marker_only,
    _recent_chat_next_state_signal_summaries,
    _record_chat_next_state_signal,
    _record_missing_session_turn_control_recovery,
    _record_provider_failure_signal,
    _remember_continuation_visible_result,
    _required_tool_progress_followup_guidance,
    _required_tool_progress_missing,
    _restore_missing_session_turn_control,
    _safe_tool_argument_details,
    _session_last_cache_composition,
    _session_ledger_visible_messages,
    _session_prompt_cache_log_fields,
    _session_prompt_cache_scope,
    _should_omit_message_from_agent_history,
    _should_prefer_history_goal_over_active_task,
    _source_collection_stage_task_allowed_tool_names,
    _source_collection_stage_task_required_tool_names,
    _task_status_from_result_contract,
    _unwrap_continuation_goal,
    _visible_reply_candidate,
    _visible_reply_matches_derived_tool_activity,
    _visible_reply_summary_candidate,
    _visible_session_runtime_notices,
    _weighted_token_allocation,
    _without_live_turn_ledger_partials,
)
from core.web.services.session.runtime_glue import (
    _active_chat_turn_id_for_session,
    _active_skill_contract_from_conversation,
    _active_skill_contract_from_invocation,
    _active_skill_runtime_context_from_contract,
    _active_task_context_chars,
    _agent_avatar_path,
    _agent_context_manifest_segments,
    _agent_context_prompt_category,
    _agent_created_by,
    _agent_direct_session_collision_owner_sort_key,
    _agent_direct_session_collision_repair_sort_key,
    _agent_directory_session_stub_for_id,
    _agent_for_direct_session,
    _agent_message_tool_result_succeeded,
    _agent_message_tool_sent_to_source,
    _agent_needs_ai_search_team_marker,
    _agent_team_identity,
    _ai_search_team_id_for_repair,
    _append_session_conversation_event,
    _append_session_runtime_notice,
    _archived_agent_for_direct_session,
    _assistant_projection_text_key,
    _build_lightweight_session_detail,
    _chat_contract_blocks_unexecuted_validation,
    _chat_result_outcome_source,
    _check_chat_turn_lease_decision,
    _clear_session_live_output,
    _clear_session_turn_control,
    _close_previous_running_status_events,
    _codex_cell_default_title,
    _codex_cell_kind,
    _codex_cell_tone,
    _codex_exit_code,
    _codex_lifecycle_status,
    _codex_operation_id,
    _codex_operation_summary,
    _codex_rollout_event,
    _codex_rollout_event_suffix,
    _codex_rollout_events_from_lifecycle,
    _codex_runtime_kind,
    _codex_terminal_operation_kind,
    _codex_terminal_request,
    _codex_terminal_result,
    _codex_terminal_session_key,
    _coerce_confidence,
    _coerce_nonnegative_int,
    _coerce_session_detail_before_index,
    _coerce_session_detail_message_limit,
    _coerce_session_query_limit,
    _coerce_tool_number,
    _compact_codex_record,
    _context_prompt_category,
    _conversation_hidden_from_index,
    _conversation_is_read_only,
    _conversation_turn_log_path,
    _create_session_turn_control,
    _current_session_live_context_composition,
    _current_session_turn_id,
    _default_session_dialogue_model_id,
    _elapsed_ms,
    _elapsed_ms_between,
    _empty_codex_tool_lifecycle_projection,
    _ensure_session_mutable,
    _ensure_session_reasoning_effort_initialized,
    _ensure_session_workspace,
    _estimate_session_context_tokens,
    _explicit_chat_result_outcome,
    _extend_codex_tool_lifecycle_projection,
    _extract_chat_tool_calls,
    _extract_missing_agent_llm_model_id,
    _find_user_message_index_by_api_id,
    _first_positive_int,
    _first_present_mapping_value,
    _get_session_stop_reason,
    _get_session_turn_control,
    _get_turn_control_stop_reason,
    _initial_session_reasoning_effort,
    _initialized_session_reasoning_effort,
    _invalidate_session_conversation_events_cache,
    _invalidate_session_list_cache,
    _is_continue_request,
    _is_effective_user_message,
    _is_meaningful_task_goal,
    _is_non_diagnostic_runtime_status_source,
    _is_protocol_only_assistant_message,
    _is_real_user_message_entry,
    _is_retriable_image_request_prompt,
    _is_session_busy_for_delete,
    _is_session_running,
    _is_session_stop_requested,
    _is_session_turn_current,
    _is_steer_guidance_message_entry,
    _is_system_authored_user_message_entry,
    _is_task_tool_backed_active_task,
    _is_task_tool_name,
    _latest_assistant_message_is_stop,
    _latest_assistant_summary,
    _latest_meaningful_user_message,
    _latest_message_timestamp,
    _latest_real_user_message,
    _latest_user_message,
    _latest_user_message_id,
    _latest_user_message_index,
    _latest_user_message_index_matching_goal,
    _latest_user_summary,
    _live_assistant_message_id,
    _live_assistant_overlay_turn_id,
    _load_active_conversation_summary_target,
    _load_session_conversation_events_cached,
    _localize_lease_conflict,
    _looks_like_agent_message_delivery_confirmation,
    _looks_like_encoding_replacement_message,
    _looks_like_structured_payload,
    _merge_codex_lifecycle_status,
    _merge_codex_terminal_sessions,
    _merge_project_paths,
    _message_content_with_attachment_summary,
    _message_metadata_kind,
    _message_turn_id,
    _missing_llm_usage,
    _normalize_message_thought,
    _normalize_project_path,
    _normalize_project_paths,
    _normalize_session_detail_transcript_scope,
    _normalize_session_kind,
    _normalize_session_query_sort,
    _normalize_session_runtime_notice,
    _normalize_string_list,
    _now_timestamp,
    _parse_agent_message_tool_result,
    _path_is_reparse_point,
    _perf_counter,
    _recent_session_guidance_context_block,
    _recent_session_guidance_summaries,
    _recent_session_steer_guidance_texts,
    _replacement_active_chat_turn_id,
    _resolve_active_agent_for_turn,
    _resolve_chat_source_log_path,
    _resolve_session_user_prompt,
    _result_has_image2_tool_call,
    _result_has_task_context_tool,
    _result_tool_names,
    _root_session_id_for_conversations,
    _sandbox_terminal_result_facts,
    _sanitize_message_content,
    _sanitize_thought_delta_text,
    _sanitize_thought_text,
    _select_existing_active_task_for_update,
    _session_context_limit,
    _session_context_limit_payload,
    _session_conversation_events_signature,
    _session_events_have_terminal_turn,
    _session_last_llm_usage,
    _session_ledger_sequence,
    _session_query_sort_key,
    _session_reasoning_effort_snapshot,
    _session_reference_prompt_block,
    _session_task_workspace_for_turn,
    _session_tool_workspace_override,
    _session_turn_agent_message_item_id,
    _session_turn_assistant_markdown_text,
    _session_turn_item_base_id,
    _session_turn_item_type_from_codex_cell,
    _session_turn_prepare_timing_log_fields,
    _session_workspace_relative_path,
    _set_or_clear_session_active_task,
    _set_session_live_context_composition,
    _set_session_running,
    _set_session_waiting_live_output,
    _short_hash,
    _skill_invocation_payload,
    _skill_runtime_context_from_invocation,
    _source_authority_ref,
    _source_collection_stage_task_context_metadata,
    _source_collection_stage_task_turn_metadata,
    _status_source_has_error_detail,
    _submit_session_cycle_message_projection,
    _supervised_completion_marker_present,
    _supervised_role_for_runtime_context,
    _supervised_runtime_tool_grants_for_context,
    _supervised_workspace_override_path,
    _task_goal_dedupe_key,
    _thought_duplicates_reply,
    _trim_tool_detail_text,
    _truncate_session_ledger_before_message,
    _validate_user_message_not_encoding_replacement,
    active_session_has_write_leases,
    has_running_sessions,
    load_session_conversation_events_snapshot,
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
    _canonicalize_session_turn_items_for_protocol,
    _stamp_turn_items_message_id,
    _slim_session_turn_items_for_window_payload,
    _build_codex_transcript_from_turn_items,
    _build_codex_transcript_projection,
    _build_window_final_answer_transcript,
    _slim_codex_transcript_for_window_payload,
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
    _public_prompt_assembly_manifest,
    _session_agent_status_payload,
    _ledger_latest_preview_messages_for_session,
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
    stream_session_events_async,
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


class _ChatStateMutationLock:
    """Serialize every facade-level chat-state mutation across processes.

    Session packs historically used ``_CHAT_STATE_LOCK`` for thread safety, but
    a separate backend process could load an old snapshot and overwrite a newly
    created conversation after the local lock released.  The facade lock is the
    common mutation boundary, so it also owns the durable file transaction for
    its complete load/mutate/save lifetime.
    """

    def __init__(self) -> None:
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def __enter__(self):
        self._thread_lock.acquire()
        transaction = chat_state_transaction(PROJECT_ROOT)
        try:
            transaction.__enter__()
        except BaseException:
            self._thread_lock.release()
            raise
        stack = getattr(self._local, "transactions", None)
        if stack is None:
            stack = []
            self._local.transactions = stack
        stack.append(transaction)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        stack = getattr(self._local, "transactions", [])
        transaction = stack.pop()
        try:
            return transaction.__exit__(exc_type, exc_value, traceback)
        finally:
            if not stack:
                self._local.transactions = []
            self._thread_lock.release()


_CHAT_STATE_LOCK = _ChatStateMutationLock()


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
reset_all_agent_test_conversations = session_agent_lifecycle_serialized(
    reset_all_agent_test_conversations
)


_RUNNING_SESSIONS_LOCK = threading.Lock()
_RUNNING_SESSION_IDS: set[str] = set()
_SESSION_ACTIVE_TURN_IDS: dict[str, str] = {}
_SESSION_ACTIVE_TURN_LEASES: dict[str, list[str]] = {}
_AGENT_INBOX_WAKE_STATE_LOCK = threading.Lock()
_AGENT_INBOX_IDLE_DRAINING_SESSION_IDS: set[str] = set()
_AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS: set[str] = set()
# P0 T3: raised from 4 to 8 so parallel Agent sessions/candidate fan-outs are not
# hard-capped below the budgetPolicy.maxParallelTasks headroom. Module has no
# settings-reading idiom for these tunables, so they stay module constants.
_SESSION_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="web-chat-turn")
_SESSION_CYCLE_PROJECTION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="web-chat-cycle-projection",
)
_SESSION_AGENT_MAX_ACTIVE_TURNS = 8
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
    r"(?:provider_protocol_error|payload_protocol_error|server_error|litellm\.|badgatewayerror|openai(?:exception|error)|"
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



_SESSION_QUERY_MAX_LIMIT = 100
_SESSION_QUERY_DEFAULT_LIMIT = 50








_AGENT_SESSION_PURGE_MANIFEST = ".purge-manifest.json"
_AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX = ".cleanup.json"


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


_SESSION_TASK_CONTEXT_TOOL_NAMES = {
    "task_create_tool",
    "task_start_tool",
    "plan_update_tool",
    "task_complete_tool",
}





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
