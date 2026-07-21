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


def _session_live_output_checkpoint_path(session_id: str) -> Path:
    return _ensure_session_workspace(session_id) / "live_output.json"


def _live_output_checkpoint_payload(state: "SessionLiveOutputState") -> dict[str, Any]:
    session_id = str(getattr(state, "session_id", "") or "").strip()
    turn_id = str(getattr(state, "turn_id", "") or "").strip()
    content = str(getattr(state, "content", "") or "")
    feedback_events = _normalize_message_feedback_events(getattr(state, "feedback_events", []) or [])
    updated_at = str(getattr(state, "updated_at", "") or "").strip() or _now_timestamp()
    payload = build_live_output_checkpoint_core_payload(
        SessionLiveOutputState(
            session_id=session_id,
            turn_id=turn_id,
            stage=str(getattr(state, "stage", "") or "").strip(),
            thought=str(getattr(state, "thought", "") or ""),
            content=content,
            mental_snapshot=_normalize_mental_snapshot(getattr(state, "mental_snapshot", None)),
            tool_calls=_normalize_message_tool_calls(getattr(state, "tool_calls", []) or []),
            feedback_events=feedback_events,
            context_composition=_normalize_session_context_composition(
                getattr(state, "context_composition", None)
            ),
            llm_payload_trace=_normalize_session_llm_payload_trace(getattr(state, "llm_payload_trace", None)),
            updated_at=updated_at,
        ),
        updated_at=updated_at,
    )
    # Facade enrichment: timeline/codex projections depend on session_service helpers.
    timeline_items = _build_message_timeline_items(
        message_id=_live_assistant_message_id(session_id, turn_id) if session_id else "",
        content=content,
        feedback_events=feedback_events,
        streaming=True,
        include_assistant_text=not any(
            str(event.get("kind") or "").strip() == "assistant_text"
            for event in feedback_events
        ),
    )
    if timeline_items:
        payload["timelineItems"] = timeline_items
    codex_transcript = _build_codex_transcript_projection(
        message_id=_live_assistant_message_id(session_id, turn_id) if session_id else "",
        content=content,
        feedback_events=feedback_events,
        tool_calls=payload.get("toolCalls") or [],
        streaming=True,
    )
    if codex_transcript:
        payload["codexTranscript"] = codex_transcript
    return payload


def _write_session_live_output_checkpoint(
    session_id: str,
    state: "SessionLiveOutputState",
    *,
    force: bool = False,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    _write_session_live_output_checkpoint_core(
        normalized_session_id,
        checkpoint_path=_session_live_output_checkpoint_path(normalized_session_id),
        build_payload=lambda: _live_output_checkpoint_payload(state),
        force=force,
        interval_seconds=_SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS,
    )


def _delete_session_live_output_checkpoint(session_id: str) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    _delete_session_live_output_checkpoint_core(
        normalized_session_id,
        checkpoint_path=_session_live_output_checkpoint_path(normalized_session_id),
    )


def _discard_session_live_output_state(session_id: str, *, turn_id: str = "") -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    _discard_session_live_output_state_core(
        normalized_session_id,
        turn_id=turn_id,
        checkpoint_path=_session_live_output_checkpoint_path(normalized_session_id),
    )


def _load_session_live_output_checkpoint(session_id: str) -> "SessionLiveOutputState | None":
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    payload = _load_session_live_output_checkpoint_payload(
        _session_live_output_checkpoint_path(normalized_session_id)
    )
    if payload is None:
        return None
    return _state_from_checkpoint_payload(
        normalized_session_id,
        payload,
        sanitize_thought=_sanitize_thought_text,
        sanitize_content=lambda value: _sanitize_message_content("assistant", value),
        normalize_mental_snapshot=_normalize_mental_snapshot,
        normalize_tool_calls=_normalize_message_tool_calls,
        normalize_feedback_events=_normalize_message_feedback_events,
        normalize_context_composition=_normalize_session_context_composition,
        normalize_llm_payload_trace=_normalize_session_llm_payload_trace,
    )


def _persist_recovered_live_output_to_chat_state(
    session_id: str,
    turn_id: str,
    state: "SessionLiveOutputState",
) -> None:
    payload = _live_output_checkpoint_payload(state)
    content = _sanitize_message_content("assistant", payload.get("content") or "")
    thought = _sanitize_thought_text(payload.get("thought") or "")
    tool_calls = _normalize_message_tool_calls(payload.get("toolCalls") or [])
    feedback_events = _normalize_message_feedback_events(payload.get("feedbackEvents") or [])
    mental_snapshot = _normalize_mental_snapshot(payload.get("mentalSnapshot"))
    if not content and not thought and not tool_calls and not feedback_events and mental_snapshot is None:
        return
    normalized_turn_id = str(turn_id or "").strip()
    with _CHAT_STATE_LOCK:
        chat_payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(chat_payload, session_id)
        if conversation is None:
            return
        if _find_turn_scoped_assistant_message(_session_ledger_visible_messages(session_id), normalized_turn_id) is not None:
            return
        assistant_entry = _make_chat_message(
            "assistant",
            content,
            tool_calls,
            thought=thought,
            feedback_events=feedback_events,
            mental_snapshot=mental_snapshot,
            metadata={"turnId": normalized_turn_id},
        )
        if tool_calls:
            assistant_entry["toolCalls"] = tool_calls
        if feedback_events:
            assistant_entry["feedbackEvents"] = feedback_events
        conversation.pop("messages", None)
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        chat_payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, chat_payload)


def _reconcile_stale_session_ledger(session_id: str, *, active_turn_id: str = "", reason: str = "process_restarted") -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    if _is_session_running(normalized_session_id):
        return
    # Process-local session state can briefly be absent while a submitted turn is
    # already durable and running. The persisted WorkRun is the cross-request
    # authority in that window; detail projection must not terminate its ledger.
    if _active_chat_turn_work_run_for_session(normalized_session_id) is not None:
        return
    recovered_from_checkpoint_only = False
    event_turn_id = ""
    try:
        events = load_conversation_events(PROJECT_ROOT, normalized_session_id)
        checkpoint = _load_session_live_output_checkpoint(normalized_session_id)
        turn_id = latest_open_turn_id(events)
        checkpoint_turn_id = str(getattr(checkpoint, "turn_id", "") or "").strip() if checkpoint is not None else ""
        checkpoint_payload = _live_output_checkpoint_payload(checkpoint) if checkpoint is not None else {}
        checkpoint_has_assistant_payload = _live_output_checkpoint_has_assistant_payload(checkpoint_payload)
        if not turn_id and checkpoint_turn_id and _session_events_have_terminal_turn(events, checkpoint_turn_id):
            _discard_session_live_output_state(normalized_session_id, turn_id=checkpoint_turn_id)
            return
        if not turn_id and checkpoint_turn_id and not checkpoint_has_assistant_payload:
            return
        if not turn_id and checkpoint_turn_id:
            turn_id = checkpoint_turn_id
            recovered_from_checkpoint_only = True
        if not turn_id:
            _discard_session_live_output_state(normalized_session_id)
            return
        if active_turn_id and turn_id == str(active_turn_id or "").strip():
            return
        if checkpoint is not None and (not checkpoint.turn_id or checkpoint.turn_id == turn_id):
            payload = checkpoint_payload
            if checkpoint_has_assistant_payload:
                _persist_recovered_live_output_to_chat_state(normalized_session_id, turn_id, checkpoint)
                _append_session_conversation_event(
                    normalized_session_id,
                    turn_id,
                    EVENT_ASSISTANT_MESSAGE,
                    status="interrupted",
                    payload={
                        "content": str(payload.get("content") or ""),
                        "thought": str(payload.get("thought") or ""),
                        "toolCalls": list(payload.get("toolCalls") or []),
                        "feedbackEvents": list(payload.get("feedbackEvents") or []),
                        "metadata": {
                            "interrupted": True,
                            "recoveredFromLiveOutputCheckpoint": True,
                        },
                    },
                    source="recover_live_output_checkpoint",
                )
        event = _append_stale_turn_interruption_if_session_inactive(
            normalized_session_id,
            turn_id,
            reason=reason,
        )
        if event is None:
            return
        event_turn_id = str(event.turn_id or turn_id)
        _invalidate_session_conversation_events_cache(normalized_session_id)
        _discard_session_live_output_state(normalized_session_id, turn_id=turn_id)
    except Exception:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "conversation_ledger",
            "conversation.ledger.reconciled_interrupted",
            level="warning",
            outcome="interrupted",
            message="Reconciled an open chat ledger turn as interrupted.",
            fields={
                "sessionId": normalized_session_id,
                "turnId": event_turn_id,
                "reason": reason,
                "recoveredFromCheckpointOnly": recovered_from_checkpoint_only,
            },
            lifecycle=True,
        )
    except Exception:
        return


def store_session_image_artifact(
    session_id: str,
    image_bytes: bytes,
    *,
    output_format: str = "png",
    source: str = "image2",
) -> dict[str, Any]:
    """Persist a generated image under the current session workspace."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionValidationError("Session id is required for image artifact storage.")
    normalized_format = str(output_format or "png").strip().lower().lstrip(".") or "png"
    if normalized_format not in _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        raise SessionValidationError("Unsupported image artifact format.")
    payload = bytes(image_bytes or b"")
    if not payload:
        raise SessionValidationError("Image artifact payload is empty.")

    with _CHAT_STATE_LOCK:
        _ensure_session_mutable(normalized_session_id)
        workspace_path = _ensure_session_workspace(normalized_session_id)
        images_dir = (workspace_path / "artifacts" / "images").resolve()
        artifacts_root = (workspace_path / "artifacts").resolve()
        images_dir.mkdir(parents=True, exist_ok=True)
        if not images_dir.is_relative_to(artifacts_root):
            raise SessionValidationError(f"Invalid session image artifact path: {images_dir}")

        artifact_id = f"{source}-{int(time.time() * 1000)}-{secrets.token_hex(4)}.{normalized_format}"
        output_path = (images_dir / artifact_id).resolve()
        if output_path.parent != images_dir:
            raise SessionValidationError("Invalid session image artifact filename.")
        output_path.write_bytes(payload)

    url = (
        f"/api/sessions/{quote(normalized_session_id, safe='')}"
        f"/artifacts/{quote(artifact_id, safe='')}"
    )
    relative_path = f"{_session_workspace_relative_path(normalized_session_id)}/artifacts/images/{artifact_id}"
    return {
        "artifactId": artifact_id,
        "filename": artifact_id,
        "artifactPath": relative_path,
        "path": str(output_path),
        "url": url,
        "imageUrl": url,
        "downloadUrl": f"{url}?download=1",
        "contentType": _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES[normalized_format],
        "sizeBytes": len(payload),
        "outputFormat": normalized_format,
    }


def store_session_user_image_attachment(
    session_id: str,
    image_bytes: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> dict[str, Any]:
    """Persist a user-uploaded image attachment under the current session workspace."""

    normalized_content_type = str(content_type or "").split(";", 1)[0].strip().lower()
    original_filename = _decode_attachment_filename(filename)
    extension = _session_image_extension_for_upload(original_filename, normalized_content_type)
    if extension not in _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        raise SessionValidationError("Unsupported image attachment format.")
    payload = bytes(image_bytes or b"")
    if not payload:
        raise SessionValidationError("Image attachment payload is empty.")
    if len(payload) > _SESSION_USER_IMAGE_MAX_BYTES:
        raise SessionValidationError("Image attachment is too large.")
    sniffed_extension = _sniff_image_extension(payload)
    if not sniffed_extension:
        raise SessionValidationError("Unsupported image attachment format.")
    extension = sniffed_extension
    normalized_content_type = _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES[extension]

    with _CHAT_STATE_LOCK:
        _ensure_session_mutable(session_id)
        artifact = store_session_image_artifact(
            session_id,
            payload,
            output_format=extension,
            source="user-image",
        )
        attachment = {
            **artifact,
            "kind": "user_image",
            "status": "ready",
            "filename": original_filename or artifact["filename"],
        }
        _remember_session_uploaded_attachment(session_id, attachment)
    _record_session_attachment_event(
        session_id,
        "stored",
        attachment,
        outcome="stored",
    )
    return attachment


def _remember_session_uploaded_attachment(session_id: str, attachment: dict[str, Any]) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        _materialize_agent_directory_conversation_locked(payload, normalized_session_id, source="store_session_user_image_attachment")
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        uploaded = list(conversation.get("uploaded_attachments") or [])
        artifact_id = str(attachment.get("artifactId") or "").strip()
        uploaded = [
            item for item in uploaded
            if not isinstance(item, dict) or str(item.get("artifactId") or "").strip() != artifact_id
        ]
        uploaded.append({key: value for key, value in attachment.items() if key != "path"})
        conversation["uploaded_attachments"] = uploaded[-24:]
        conversation["updated_at"] = _now_timestamp()
        payload["updated_at"] = conversation["updated_at"]
        save_chat_state(PROJECT_ROOT, payload)


def _decode_attachment_filename(filename: str) -> str:
    raw = str(filename or "").strip()
    if "%" not in raw:
        return Path(raw).name
    try:
        from urllib.parse import unquote

        return Path(unquote(raw)).name
    except Exception:
        return Path(raw).name


def _session_image_extension_for_upload(filename: str, content_type: str) -> str:
    extension = Path(str(filename or "")).suffix.lower().lstrip(".")
    if extension == "jpeg":
        extension = "jpg"
    if extension in _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES:
        return extension
    for known_extension, known_type in _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES.items():
        if str(content_type or "").lower() == known_type:
            return "jpg" if known_extension == "jpeg" else known_extension
    return extension


def _sniff_image_extension(payload: bytes) -> str:
    data = bytes(payload or b"")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def resolve_session_image_artifact(session_id: str, artifact_id: str) -> tuple[Path, str]:
    normalized_session_id = str(session_id or "").strip()
    normalized_artifact_id = str(artifact_id or "").strip()
    if not normalized_session_id or not normalized_artifact_id:
        raise FileNotFoundError("missing session artifact")
    artifact_name = Path(normalized_artifact_id).name
    if artifact_name != normalized_artifact_id or not _SESSION_IMAGE_ARTIFACT_SAFE_CHARS.fullmatch(artifact_name):
        raise FileNotFoundError("invalid session artifact")
    extension = Path(artifact_name).suffix.lower().lstrip(".")
    content_type = _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES.get(extension)
    if not content_type:
        raise FileNotFoundError("unsupported session artifact")

    sessions_root = developer_sandbox.sandboxed_workspace_path(PROJECT_ROOT, "sessions").resolve()
    workspace_path = _ensure_session_workspace(normalized_session_id).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise FileNotFoundError("invalid session artifact path")
    images_dir = (workspace_path / "artifacts" / "images").resolve()
    target_path = (images_dir / artifact_name).resolve()
    if not target_path.is_relative_to(images_dir) or not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError("session artifact not found")
    return target_path, content_type


def _resolve_session_image_attachment(session_id: str, artifact_id: str) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    normalized_artifact_id = str(artifact_id or "").strip()
    path, content_type = resolve_session_image_artifact(normalized_session_id, normalized_artifact_id)
    url = (
        f"/api/sessions/{quote(normalized_session_id, safe='')}"
        f"/artifacts/{quote(Path(normalized_artifact_id).name, safe='')}"
    )
    relative_path = (
        f"{_session_workspace_relative_path(normalized_session_id)}"
        f"/artifacts/images/{Path(normalized_artifact_id).name}"
    )
    return {
        "artifactId": Path(normalized_artifact_id).name,
        "filename": Path(normalized_artifact_id).name,
        "artifactPath": relative_path,
        "path": str(path),
        "url": url,
        "imageUrl": url,
        "downloadUrl": f"{url}?download=1",
        "contentType": content_type,
        "sizeBytes": path.stat().st_size,
        "kind": "user_image",
        "status": "ready",
    }


def resolve_session_image_attachment_data_url(session_id: str, artifact_id: str) -> dict[str, Any]:
    """Read a session image artifact as a transient data URL for model input."""

    attachment = _resolve_session_image_attachment(session_id, artifact_id)
    path = Path(str(attachment.get("path") or ""))
    payload = path.read_bytes()
    if len(payload) > _SESSION_USER_IMAGE_MAX_BYTES:
        raise SessionValidationError("Image attachment is too large for model input.")
    content_type = str(attachment.get("contentType") or "").strip() or "image/png"
    data_url = f"data:{content_type};base64,{base64.b64encode(payload).decode('ascii')}"
    return {
        **{key: value for key, value in attachment.items() if key != "path"},
        "dataUrl": data_url,
    }


def _resolve_session_image_attachments(
    session_id: str,
    attachment_ids: Any,
    *,
    conversation: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in list(attachment_ids or []):
        artifact_id = str(raw_id or "").strip()
        if not artifact_id or artifact_id in seen:
            continue
        seen.add(artifact_id)
        normalized_ids.append(artifact_id)
    if len(normalized_ids) > _SESSION_USER_IMAGE_MAX_ATTACHMENTS_PER_TURN:
        raise SessionValidationError("Too many image attachments for one turn.")
    attachments: list[dict[str, Any]] = []
    for artifact_id in normalized_ids:
        existing = _find_session_attachment_metadata(conversation, artifact_id)
        if existing:
            attachments.append(existing)
            continue
        try:
            attachments.append(_resolve_session_image_attachment(session_id, artifact_id))
        except FileNotFoundError as exc:
            raise SessionValidationError(f"Image attachment not found: {artifact_id}") from exc
    return attachments


def _find_session_attachment_metadata(conversation: dict[str, Any] | None, artifact_id: str) -> dict[str, Any]:
    if not isinstance(conversation, dict):
        return {}
    normalized_artifact_id = str(artifact_id or "").strip()
    if not normalized_artifact_id:
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for message in reversed(_session_ledger_visible_messages(conversation_id)):
        if not isinstance(message, dict):
            continue
        for attachment in _normalize_message_attachments(message.get("attachments") or []):
            if str(attachment.get("artifactId") or "").strip() == normalized_artifact_id:
                return dict(attachment)
    for attachment in reversed(list(conversation.get("uploaded_attachments") or [])):
        if not isinstance(attachment, dict):
            continue
        normalized = _normalize_message_attachments([attachment])
        if normalized and str(normalized[0].get("artifactId") or "").strip() == normalized_artifact_id:
            return dict(normalized[0])
    return {}


def _has_recent_image_attachment_reference(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    if _contains_any_attachment_reference_pattern(normalized, _RECENT_IMAGE_REFERENCE_EXACT_PATTERNS):
        return True
    has_reference = _contains_any_attachment_reference_pattern(normalized, _RECENT_IMAGE_REFERENCE_WORDS)
    has_image_target = _contains_any_attachment_reference_pattern(normalized, _RECENT_IMAGE_TARGET_WORDS)
    return has_reference and has_image_target


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


def _find_recent_user_image_attachment(conversation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(conversation, dict):
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for message in reversed(_session_ledger_visible_messages(conversation_id)):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        attachments = _normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
        for attachment in reversed(attachments):
            if _is_ready_user_image_attachment(attachment):
                return dict(attachment)
    for attachment in reversed(list(conversation.get("uploaded_attachments") or [])):
        normalized = _normalize_message_attachments([attachment])
        if normalized and _is_ready_user_image_attachment(normalized[0]):
            return dict(normalized[0])
    return {}


def _is_ready_user_image_attachment(attachment: dict[str, Any]) -> bool:
    if not isinstance(attachment, dict):
        return False
    artifact_id = str(attachment.get("artifactId") or "").strip()
    status = str(attachment.get("status") or "ready").strip().lower()
    kind = str(attachment.get("kind") or "user_image").strip().lower()
    content_type = str(attachment.get("contentType") or "").strip().lower()
    return bool(artifact_id) and status == "ready" and kind == "user_image" and (
        not content_type or content_type.startswith("image/")
    )


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


def _ensure_conversation_workspace_metadata(conversation: dict[str, Any]) -> bool:
    conversation_id = str(conversation.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return False
    workspace_path = _session_workspace_relative_path(conversation_id)
    _ensure_session_workspace(conversation_id)
    changed = conversation.get("workspace_path") != workspace_path
    if changed:
        conversation["workspace_path"] = workspace_path
    return changed


def _conversation_index_kind_from_raw(raw: dict[str, Any]) -> tuple[str, str]:
    raw_kind = str(raw.get("conversation_index_kind") or raw.get("conversationIndexKind") or "").strip()
    return raw_kind, agent_directory_service.normalize_conversation_index_kind(raw_kind)


def _conversation_index_classification(
    raw: dict[str, Any],
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    raw_kind, normalized_raw_kind = _conversation_index_kind_from_raw(raw)
    errors: list[str] = []
    if raw_kind and not normalized_raw_kind:
        errors.append("invalid_conversation_index_kind")

    agent_classification = (
        agent_directory_service.agent_conversation_index_classification(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        if isinstance(agent, dict)
        else {"kind": agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}
    )
    agent_kind = str(agent_classification.get("kind") or "").strip()
    agent_errors = list(agent_classification.get("errors") or [])

    if normalized_raw_kind:
        kind = normalized_raw_kind
        if (
            isinstance(agent, dict)
            and agent_kind
            and agent_kind not in {
                agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
                agent_directory_service.CONVERSATION_INDEX_KIND_INVALID,
            }
            and agent_kind != kind
        ):
            errors.append("conversation_agent_index_kind_conflict")
    elif isinstance(agent, dict) and agent_kind != agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        kind = agent_kind
        errors.extend(agent_errors)
    else:
        kind = agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
        errors.append("missing_conversation_index_kind")

    if kind in {
        agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
        agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
    } and not isinstance(agent, dict):
        errors.append("agent_required_for_agent_index_kind")
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT and isinstance(agent, dict):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        has_team_marker = bool(
            str(metadata.get("teamId") or "").strip()
            or str(metadata.get("challengeCupTeamId") or "").strip()
            or str(metadata.get("knowledgeExpansionTeamId") or "").strip()
        )
        if not has_team_marker:
            errors.append("team_agent_missing_team_id")
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        errors.extend(agent_errors)

    errors = sorted(set(str(item) for item in errors if str(item or "").strip()))
    if errors and kind != agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        kind = agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
    return {"kind": kind, "errors": errors}


def repair_conversation_index_records() -> dict[str, Any]:
    """Explicitly migrate legacy direct-agent conversation index records.

    This is intentionally not part of the read path. Missing or invalid records
    still surface as invalid until this migration is called.
    """

    _sync_agent_directory_project_root()
    hidden_team_member_agent_ids = _agent_directory_stub_hidden_team_member_ids()
    state = agent_directory_service.load_state()
    agents = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
    repaired_agents: list[dict[str, str]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        repair_kind = _legacy_agent_conversation_index_repair_kind(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        if not repair_kind:
            continue
        _apply_agent_conversation_index_repair_metadata(agent, repair_kind)
        agent["updatedAt"] = agent_directory_service.utc_now_iso()
        repaired_agents.append(
            {
                "agentId": str(agent.get("agentId") or "").strip(),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "kind": repair_kind,
            }
        )
    if repaired_agents:
        state["agents"] = agents
        agent_directory_service.save_state(state)

    payload = load_chat_state(PROJECT_ROOT)
    conversations = payload.get("conversations")
    repaired_conversations: list[dict[str, str]] = []
    agent_by_id = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    if isinstance(conversations, list):
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            raw_kind, normalized_raw_kind = _conversation_index_kind_from_raw(conversation)
            if raw_kind and not normalized_raw_kind:
                continue
            agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
            agent = agent_by_id.get(agent_id)
            if not isinstance(agent, dict):
                continue
            agent_classification = agent_directory_service.agent_conversation_index_classification(
                agent,
                hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            )
            agent_kind = str(agent_classification.get("kind") or "").strip()
            if agent_kind not in {
                agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
                agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
                agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
            }:
                continue
            if normalized_raw_kind == agent_kind and _conversation_repair_flags_match_kind(conversation, agent_kind):
                continue
            _apply_conversation_index_repair_fields(conversation, agent_kind)
            repaired_conversations.append(
                {
                    "sessionId": str(conversation.get("conversation_id") or "").strip(),
                    "agentId": agent_id,
                    "kind": agent_kind,
                }
            )
    if repaired_conversations:
        save_chat_state(PROJECT_ROOT, payload)

    if repaired_agents or repaired_conversations:
        _invalidate_session_list_cache()
    result = {
        "changed": bool(repaired_agents or repaired_conversations),
        "agentCount": len(repaired_agents),
        "conversationCount": len(repaired_conversations),
        "agents": repaired_agents,
        "conversations": repaired_conversations,
    }
    if result["changed"]:
        try:
            record_runtime_scene_event(
                "conversation",
                "session_lifecycle",
                "conversation.index.repaired",
                level="info",
                outcome="succeeded",
                message="Conversation index records repaired.",
                fields={
                    "agentCount": result["agentCount"],
                    "conversationCount": result["conversationCount"],
                },
                lifecycle=True,
            )
        except Exception:
            pass
    return result


def _legacy_agent_conversation_index_repair_kind(
    agent: dict[str, Any],
    *,
    hidden_team_member_agent_ids: set[str],
) -> str:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw_kind = str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip()
    agent_id = str(agent.get("agentId") or "").strip()
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
    if raw_kind:
        # API-created direct Agents used to inherit the generic user_chat
        # default. That classification is invalid for a direct Agent and hid
        # the record from the personal-Agent directory. Other explicit kinds
        # remain authoritative and are never rewritten by this repair.
        if not (
            raw_kind == agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT
            and created_by == "api_agents"
        ):
            return ""
    if created_by in agent_directory_service.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY:
        return agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
    if created_by == "session_repair":
        return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    role_key = str(agent.get("roleKey") or "").strip()
    has_team_marker = bool(
        str(metadata.get("teamId") or "").strip()
        or str(metadata.get("challengeCupTeamId") or "").strip()
        or str(metadata.get("knowledgeExpansionTeamId") or "").strip()
        or (agent_id and agent_id in hidden_team_member_agent_ids)
    )
    looks_team_owned = (
        has_team_marker
        or role_key.startswith("challenge_cup_")
        or role_key.startswith("knowledge_expansion_")
        or created_by in agent_directory_service.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY
    )
    if looks_team_owned:
        return agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
    if created_by == "api_agents" and str(agent.get("directSessionId") or "").strip():
        return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    return ""


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


def _apply_agent_conversation_index_repair_metadata(agent: dict[str, Any], kind: str) -> None:
    metadata = dict(agent.get("metadata") or {})
    metadata["conversationIndexKind"] = kind
    metadata["conversationIndexVisibility"] = _conversation_index_visibility_for_kind(kind)
    if kind in {
        agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
    }:
        metadata["showInSessionIndex"] = False
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        metadata.setdefault("directSessionVisibility", "active_session")
        if _agent_needs_ai_search_team_marker(agent, metadata):
            metadata.setdefault("teamId", _ai_search_team_id_for_repair())
    agent["metadata"] = metadata


def _conversation_repair_flags_match_kind(conversation: dict[str, Any], kind: str) -> bool:
    hidden_flag = bool(conversation.get("hidden_from_index") or conversation.get("hiddenFromIndex"))
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return hidden_flag
    return not hidden_flag


def _apply_conversation_index_repair_fields(conversation: dict[str, Any], kind: str) -> None:
    conversation["conversation_index_kind"] = kind
    conversation["conversationIndexKind"] = kind
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    else:
        conversation["hidden_from_index"] = False
        conversation["hiddenFromIndex"] = False


def _conversation_index_visibility_for_kind(kind: str) -> str:
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        return agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    return agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE


def _conversation_index_visibility_for_classification(
    kind: str,
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> str:
    normalized_kind = str(kind or "").strip()
    if normalized_kind and normalized_kind != agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        return _conversation_index_visibility_for_kind(normalized_kind)
    if isinstance(agent, dict):
        return agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
    return agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE


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


def _raw_conversation_session_kind(conversation: dict[str, Any]) -> str:
    return _normalize_session_kind(conversation.get("session_kind") or conversation.get("sessionKind"))


def _raw_conversation_root_session_id(conversation: dict[str, Any], conversation_id: str) -> str:
    parent_session_id = str(conversation.get("parent_session_id") or conversation.get("parentSessionId") or "").strip()
    root_session_id = str(conversation.get("root_session_id") or conversation.get("rootSessionId") or "").strip()
    if root_session_id:
        return root_session_id
    if _raw_conversation_session_kind(conversation) == "child" and parent_session_id:
        return parent_session_id
    return conversation_id


def _conversation_agent_direct_session_is_allowed(
    *,
    conversation: dict[str, Any],
    conversation_id: str,
    direct_session_id: str,
) -> bool:
    if not direct_session_id or direct_session_id == conversation_id:
        return True
    if str(conversation.get("session_role") or conversation.get("sessionRole") or "").strip() == "workspace":
        return True
    session_kind = _raw_conversation_session_kind(conversation)
    if session_kind == "child":
        root_id = _raw_conversation_root_session_id(conversation, conversation_id)
        parent_id = str(conversation.get("parent_session_id") or conversation.get("parentSessionId") or "").strip()
        return direct_session_id in {root_id, parent_id}
    return False


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


def _repair_conversation_agent_legacy_model_fields(
    conversation: dict[str, Any],
    *,
    conversation_id: str,
    agent_id: str,
    agent: dict[str, Any] | None = None,
) -> bool:
    previous_fields = {
        "agent_profile_id": str(conversation.get("agent_profile_id") or "").strip(),
        "agentProfileId": str(conversation.get("agentProfileId") or "").strip(),
        "agentTemplateId": str(conversation.get("agentTemplateId") or "").strip(),
        "agentTemplateLabel": str(conversation.get("agentTemplateLabel") or "").strip(),
    }
    changed = False
    for key in ("agent_profile_id", "agentProfileId", "agentTemplateId", "agentTemplateLabel"):
        if key in conversation:
            conversation.pop(key, None)
            changed = True
    if changed:
        _record_session_agent_legacy_model_fields_repaired_event(
            conversation_id,
            agent_id=agent_id,
            previous_fields=previous_fields,
            prompt_template_id=str((agent or {}).get("promptTemplateId") or "").strip(),
            role_key=str((agent or {}).get("roleKey") or "").strip(),
        )
    return changed


def _ensure_conversation_agent_metadata(
    conversation: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    _sync_agent_directory_project_root()
    conversation_id = str(conversation.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return False
    title = str(conversation.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip() or DEFAULT_CHAT_CONVERSATION_TITLE
    session_workspace = str(conversation.get("workspace_path") or _session_workspace_relative_path(conversation_id))
    existing_agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    session_kind = _raw_conversation_session_kind(conversation)
    agent_status_code = str(conversation.get("agentStatusCode") or "").strip()
    if agent_status_code == "deleted_agent":
        deleted_agent_id = str(
            conversation.get("agent_deleted_id")
            or conversation.get("agentDeletedId")
            or conversation.get("agent_missing_id")
            or conversation.get("agentMissingId")
            or existing_agent_id
            or ""
        ).strip()
        changed = False
        for key in ("agent_id", "agentId"):
            if conversation.get(key) != "":
                conversation[key] = ""
                changed = True
        for key in ("agent_deleted_id", "agentDeletedId", "agent_missing_id", "agentMissingId"):
            if deleted_agent_id and conversation.get(key) != deleted_agent_id:
                conversation[key] = deleted_agent_id
                changed = True
        if conversation.get("agentMissing") is not True:
            conversation["agentMissing"] = True
            changed = True
        if conversation.get("agentStatusCode") != "deleted_agent":
            conversation["agentStatusCode"] = "deleted_agent"
            changed = True
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        if conversation.get("agentPrimaryDirectSessionId"):
            conversation["agentPrimaryDirectSessionId"] = ""
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=deleted_agent_id,
        ) or changed
        return changed
    existing_agent = _agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
    if existing_agent is None:
        recovered_agent = _recover_active_direct_session_agent(
            conversation_id,
            agent_by_id=agent_by_id,
            preferred_agent_id=(
                existing_agent_id
                or str(conversation.get("agent_missing_id") or conversation.get("agentMissingId") or "").strip()
            ),
        )
        if recovered_agent is not None:
            existing_agent = recovered_agent
            existing_agent_id = str(recovered_agent.get("agentId") or "").strip()
    default_primary_mode = agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE
    primary_mode = str((existing_agent or {}).get("primaryMode") or default_primary_mode).strip() or default_primary_mode
    role_key = str((existing_agent or {}).get("roleKey") or "").strip()
    prompt_template_id = str((existing_agent or {}).get("promptTemplateId") or "").strip()
    if existing_agent_id and not existing_agent:
        changed = False
        if conversation.get("agent_id") != "":
            conversation["agent_id"] = ""
            changed = True
        if conversation.get("agentId") != "":
            conversation["agentId"] = ""
            changed = True
        if conversation.get("agent_missing_id") != existing_agent_id:
            conversation["agent_missing_id"] = existing_agent_id
            changed = True
        if conversation.get("agentMissingId") != existing_agent_id:
            conversation["agentMissingId"] = existing_agent_id
            changed = True
        if conversation.get("agentMissing") is not True:
            conversation["agentMissing"] = True
            changed = True
        if conversation.get("agentStatusCode") != "missing_agent":
            conversation["agentStatusCode"] = "missing_agent"
            changed = True
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
        ) or changed
        return changed
    if existing_agent and str(existing_agent.get("status") or "active").strip().lower() == "archived":
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        return changed
    if existing_agent and str(existing_agent.get("directSessionId") or "").strip() == conversation_id:
        changed = False
        recovered_missing_agent = bool(
            conversation.get("agentMissing")
            or conversation.get("agentStatusCode")
            or conversation.get("agent_missing_id")
            or conversation.get("agentMissingId")
        )
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        for key in ("agent_missing_id", "agentMissingId"):
            if conversation.get(key):
                conversation[key] = ""
                changed = True
        if conversation.get("agentMissing"):
            conversation["agentMissing"] = False
            changed = True
        if conversation.get("agentStatusCode"):
            conversation["agentStatusCode"] = ""
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        if conversation.get("agentPrimaryDirectSessionId"):
            conversation["agentPrimaryDirectSessionId"] = ""
            changed = True
        if recovered_missing_agent and changed:
            _record_session_agent_binding_recovered_event(conversation_id, agent_id=existing_agent_id)
        return changed
    if existing_agent:
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        existing_direct_session_id = str(existing_agent.get("directSessionId") or "").strip()
        child_session_ids = _raw_conversation_child_session_ids(conversation)
        if (
            session_kind != "child"
            and existing_direct_session_id
            and existing_direct_session_id in child_session_ids
        ):
            previous_direct_session_id = existing_direct_session_id
            repaired_agent = ensure_agent_for_session(
                conversation_id,
                display_name=title,
                llm_bindings=agent_directory_service.normalize_agent_llm_bindings(existing_agent.get("llmBindings")),
                primary_mode=primary_mode,
                role_key=role_key,
                prompt_template_id=prompt_template_id,
                existing_agent_id=existing_agent_id,
                session_workspace_path=session_workspace,
            )
            existing_agent = _conversation_agent_from_state(repaired_agent)
            if agent_by_id is not None:
                agent_by_id[existing_agent_id] = existing_agent
            existing_direct_session_id = str(existing_agent.get("directSessionId") or "").strip()
            changed = True
            _record_session_agent_child_direct_binding_repaired_event(
                conversation_id,
                agent_id=existing_agent_id,
                previous_direct_session_id=previous_direct_session_id,
            )
        if _conversation_agent_direct_session_is_allowed(
            conversation=conversation,
            conversation_id=conversation_id,
            direct_session_id=existing_direct_session_id,
        ):
            if conversation.get("agentDirectSessionMismatch"):
                conversation["agentDirectSessionMismatch"] = False
                changed = True
            if conversation.get("agentPrimaryDirectSessionId"):
                conversation["agentPrimaryDirectSessionId"] = ""
                changed = True
        elif existing_direct_session_id:
            if conversation.get("agentDirectSessionMismatch") is not True:
                conversation["agentDirectSessionMismatch"] = True
                changed = True
            if conversation.get("agentPrimaryDirectSessionId") != existing_direct_session_id:
                conversation["agentPrimaryDirectSessionId"] = existing_direct_session_id
                changed = True
        return changed
    if existing_agent:
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        return changed
    archived_direct_agent = _archived_agent_for_direct_session(conversation_id) if not existing_agent_id else None
    if archived_direct_agent:
        archived_agent_id = str(archived_direct_agent.get("agentId") or "").strip()
        changed = False
        if conversation.get("agent_id") != archived_agent_id:
            conversation["agent_id"] = archived_agent_id
            changed = True
        if conversation.get("agentId") != archived_agent_id:
            conversation["agentId"] = archived_agent_id
            changed = True
        changed = _repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=archived_agent_id,
            agent=archived_direct_agent,
        ) or changed
        return changed
    direct_agent = _agent_for_direct_session(conversation_id) if not existing_agent_id else None
    if not direct_agent and not _conversation_requires_agent_materialization(conversation):
        return False
    llm_bindings_for_ensure = (
        agent_directory_service.normalize_agent_llm_bindings(existing_agent.get("llmBindings"))
        if existing_agent
        else agent_directory_service.normalize_agent_llm_bindings((direct_agent or {}).get("llmBindings"))
    )
    if not llm_bindings_for_ensure and not direct_agent:
        llm_bindings_for_ensure = _normalize_session_agent_llm_bindings(None)
    agent = ensure_agent_for_session(
        conversation_id,
        display_name=title,
        llm_bindings=llm_bindings_for_ensure,
        primary_mode=primary_mode,
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        existing_agent_id=existing_agent_id,
        session_workspace_path=session_workspace,
    )
    agent_id = str(agent.get("agentId") or "").strip()
    if agent_by_id is not None and agent_id:
        agent_by_id[agent_id] = agent
    changed = False
    if agent_id and conversation.get("agent_id") != agent_id:
        conversation["agent_id"] = agent_id
        changed = True
    if agent_id and conversation.get("agentId") != agent_id:
        conversation["agentId"] = agent_id
        changed = True
    changed = _repair_conversation_agent_legacy_model_fields(
        conversation,
        conversation_id=conversation_id,
        agent_id=agent_id,
        agent=agent,
    ) or changed
    return changed


def _conversation_requires_agent_materialization(conversation: dict[str, Any]) -> bool:
    if str(conversation.get("agent_id") or conversation.get("agentId") or "").strip():
        return True
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if list(conversation.get("messages") or []):
        return True
    if conversation_id.startswith("session-seed-"):
        return False
    if "workspace_path" not in conversation and "workspacePath" not in conversation:
        return True
    if conversation_id and _session_ledger_visible_messages(conversation_id):
        return True
    active_task = conversation.get("active_task") or conversation.get("activeTask")
    if isinstance(active_task, dict) and active_task:
        return True
    if str(conversation.get("session_kind") or conversation.get("sessionKind") or "").strip().lower() in {"child", "supervised"}:
        return True
    last_status = str(conversation.get("last_turn_status") or conversation.get("status") or "").strip().lower()
    return last_status not in {"", "ready", "idle"}


def _sync_agent_directory_project_root() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT
        _invalidate_session_list_cache()


def _conversation_agent_from_state(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    team_identity = _agent_team_identity(agent, metadata)
    workspace_path = str(agent.get("workspacePath") or "").strip()
    avatar_path = _agent_avatar_path(agent, metadata)
    llm_bindings = agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings"))
    return {
        "agentId": agent_id,
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or agent_directory_service.DEFAULT_AGENT_KIND).strip()
        or agent_directory_service.DEFAULT_AGENT_KIND,
        "primaryMode": str(agent.get("primaryMode") or agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE).strip()
        or agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE,
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
        "llmBindings": llm_bindings,
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "conversationIndexKind": str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip(),
        "teamId": str(team_identity.get("teamId") or "").strip(),
        "teamName": str(team_identity.get("teamName") or "").strip(),
        "workspacePath": workspace_path,
        "avatarImagePath": avatar_path,
        "avatarImageUrl": agent_directory_service.agent_avatar_image_url(avatar_path),
        "status": str(agent.get("status") or "active").strip() or "active",
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "metadata": dict(metadata),
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
    }


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


def _agent_from_lookup(
    agent_by_id: dict[str, dict[str, Any]] | None,
    agent_id: str,
) -> dict[str, Any] | None:
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    if agent_by_id is not None:
        agent = agent_by_id.get(normalized)
        return agent if isinstance(agent, dict) else None
    return get_agent(normalized)


def _recover_active_direct_session_agent(
    session_id: str,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None,
    preferred_agent_id: str = "",
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or not isinstance(agent_by_id, dict):
        return None
    normalized_preferred_agent_id = str(preferred_agent_id or "").strip()
    preferred_agent = _agent_from_lookup(agent_by_id, normalized_preferred_agent_id) if normalized_preferred_agent_id else None
    if (
        isinstance(preferred_agent, dict)
        and str(preferred_agent.get("status") or "active").strip().lower() != "archived"
        and str(preferred_agent.get("directSessionId") or "").strip() == normalized_session_id
    ):
        return preferred_agent
    for agent in agent_by_id.values():
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        if str(agent.get("directSessionId") or "").strip() == normalized_session_id:
            return agent
    return None


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


def _session_agent_is_available(summary: dict[str, Any]) -> bool:
    return bool(str(summary.get("agentId") or "").strip()) and not bool(summary.get("agentMissing"))


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


def _get_cached_session_query_sessions(*, now: float) -> list[dict[str, Any]] | None:
    _sync_agent_directory_project_root()
    signature = (_session_list_source_signature(), False)
    if _repair_agent_direct_session_collisions(source_signature=signature):
        signature = (_session_list_source_signature(), False)
    cached = _get_session_list_cache(
        now=now,
        signature=signature,
        allow_stale_matching_signature=True,
    )
    if cached is None:
        return None
    sessions, cache_age_ms, conversation_count, agent_count = cached
    _record_session_list_loaded_event(
        session_count=len(sessions),
        conversation_count=conversation_count,
        agent_count=agent_count,
        elapsed_ms=_elapsed_ms(now),
        cache_hit=True,
        cache_age_ms=cache_age_ms,
        cache_ttl_ms=int(round(_SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
        waited_for_inflight=False,
    )
    return sessions


def query_sessions(
    *,
    limit: int = _SESSION_QUERY_DEFAULT_LIMIT,
    cursor: str = "",
    q: str = "",
    agent_id: str = "",
    session_kind: str = "",
    state: str = "",
    sort: str = "updatedAt_desc",
) -> dict[str, Any]:
    """Return a paginated, filtered session summary payload."""

    started_at = _perf_counter()
    sessions = _get_cached_session_query_sessions(now=started_at)
    if sessions is None:
        sessions = list_sessions()
    normalized_limit = _coerce_session_query_limit(limit)
    normalized_cursor = _coerce_nonnegative_int(cursor)
    normalized_query = str(q or "").strip().lower()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_kind = str(session_kind or "").strip().lower()
    normalized_state = str(state or "").strip().lower()
    normalized_sort = _normalize_session_query_sort(sort)

    has_filters = bool(normalized_query or normalized_agent_id or normalized_session_kind or normalized_state)
    if not has_filters and normalized_sort == "updatedAt_desc":
        filtered = sessions
    else:
        filtered = [
            item
            for item in sessions
            if _session_query_matches(
                item,
                query=normalized_query,
                agent_id=normalized_agent_id,
                session_kind=normalized_session_kind,
                state=normalized_state,
            )
        ]
    if normalized_sort != "updatedAt_desc":
        filtered.sort(
            key=_session_query_sort_key(normalized_sort),
            reverse=normalized_sort.endswith("_desc"),
        )

    total = len(filtered)
    start = min(normalized_cursor, total)
    end = min(start + normalized_limit, total)
    page_items = filtered[start:end]
    next_cursor = str(end) if end < total else ""
    _record_session_list_query_event(
        result_count=len(page_items),
        matched_count=total,
        total_count=len(sessions),
        limit=normalized_limit,
        cursor=start,
        elapsed_ms=_elapsed_ms(started_at),
        has_query=bool(normalized_query),
        has_agent_filter=bool(normalized_agent_id),
        has_kind_filter=bool(normalized_session_kind),
        has_state_filter=bool(normalized_state),
        sort=normalized_sort,
    )
    return {
        "items": page_items,
        "nextCursor": next_cursor,
        "totalEstimate": total,
        "filters": {
            "q": str(q or "").strip(),
            "agentId": normalized_agent_id,
            "sessionKind": normalized_session_kind,
            "state": normalized_state,
            "sort": normalized_sort,
            "limit": normalized_limit,
            "cursor": str(start) if start > 0 else "",
        },
    }


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


def get_session_turn_completion_snapshot(session_id: str, turn_id: str = "") -> dict[str, Any]:
    """Return a turn-scoped completion snapshot for external harness pollers."""

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        return {
            "sessionId": "",
            "turnId": normalized_turn_id,
            "terminal": False,
            "terminalStatus": "",
            "completionSource": "missing_session_id",
            "completionRecovered": False,
            "assistantText": "",
            "lastTurnStatus": "",
            "messageCount": 0,
            "isRunning": False,
            "activeTurnId": "",
            "turnCurrent": False,
        }

    with _RUNNING_SESSIONS_LOCK:
        is_running = normalized_session_id in _RUNNING_SESSION_IDS
        active_turn_id = str(_SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
    turn_current = bool(is_running and (not normalized_turn_id or active_turn_id == normalized_turn_id))

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        payload = _repair_stale_running_conversations(payload)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return {
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "terminal": False,
                "terminalStatus": "",
                "completionSource": "missing_conversation",
                "completionRecovered": False,
                "assistantText": "",
                "lastTurnStatus": "",
                "messageCount": 0,
                "isRunning": is_running,
                "activeTurnId": active_turn_id,
                "turnCurrent": turn_current,
            }
        last_turn_status = str(conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or "").strip().lower()
        messages = _session_ledger_visible_messages(session_id)

    assistant_message = _find_turn_scoped_assistant_message(messages, normalized_turn_id)
    assistant_text = str((assistant_message or {}).get("content") or "").strip()
    assistant_turn_id = _message_turn_id(assistant_message)
    marker_present = _supervised_completion_marker_present(assistant_text)
    terminal_statuses = {
        "ready",
        "completed",
        "done",
        "success",
        "failed",
        "failed_provider",
        "failed_runtime",
        "paused_limit",
        "stopped",
        "stopped_by_user",
        "cancelled",
        "needs_continue",
        "superseded",
    }
    terminal = False
    terminal_status = ""
    completion_source = "running"
    completion_recovered = False
    if last_turn_status in terminal_statuses:
        terminal = True
        terminal_status = last_turn_status
        completion_source = "last_turn_status"
    elif marker_present and assistant_text and not turn_current:
        terminal = True
        terminal_status = "ready"
        completion_source = "assistant_marker"
        completion_recovered = True
    return {
        "sessionId": normalized_session_id,
        "turnId": normalized_turn_id,
        "terminal": terminal,
        "terminalStatus": terminal_status,
        "completionSource": completion_source,
        "completionRecovered": completion_recovered,
        "assistantText": assistant_text,
        "assistantMessageFound": assistant_message is not None,
        "assistantTurnId": assistant_turn_id,
        "lastTurnStatus": last_turn_status,
        "messageCount": len(messages),
        "isRunning": is_running,
        "activeTurnId": active_turn_id,
        "turnCurrent": turn_current,
    }


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


def select_chat_session(session_id: str) -> dict:
    """Make an existing or AgentDirectory direct session the active chat session."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise SessionNotFoundError("Session not found")
    _sync_agent_directory_project_root()
    agent_by_id = _agent_lookup_for_conversations()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        changed = False
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            changed = _materialize_agent_directory_conversation_locked(
                payload,
                normalized_session_id,
                source="select_chat_session",
                activate=True,
            )
            if not changed:
                raise SessionNotFoundError("Session not found")
            conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError("Session not found")
        _ensure_session_mutable(normalized_session_id, conversation=conversation)
        changed = _ensure_conversation_workspace_metadata(conversation) or changed
        changed = _ensure_conversation_agent_metadata(conversation, agent_by_id=agent_by_id) or changed
        previous_active_id = str(payload.get("active_conversation_id") or "").strip()
        if previous_active_id != normalized_session_id:
            payload["active_conversation_id"] = normalized_session_id
            changed = True
        if changed:
            payload["updated_at"] = str(conversation.get("updated_at") or _now_timestamp())
            save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    detail = get_session_detail(normalized_session_id)
    if detail is None:
        raise SessionNotFoundError("Session not found")
    return detail


def create_chat_session(
    *,
    title: str = "",
    agent_id: str = "",
    llm_bindings: dict[str, Any] | None = None,
    created_by: str = "user",
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT,
) -> dict:
    """Create a new empty chat session and make it active."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_llm_bindings = _normalize_session_agent_llm_bindings(llm_bindings)
    bound_agent: dict[str, Any] | None = None
    if normalized_agent_id:
        _sync_agent_directory_project_root()
        bound_agent = get_agent(normalized_agent_id, include_archived=False)
        if not bound_agent:
            raise SessionValidationError(_session_agent_unavailable_message("missing_agent", lang=lang))
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = _now_timestamp()
        session_id = _new_conversation_id(existing_ids)
        normalized_title = trim_lines(title or "", max_lines=1).strip() or text_for(lang, zh="新会话", en="New session")
        conversation = _make_empty_conversation(
            session_id,
            title=normalized_title,
            timestamp=now,
            conversation_index_kind=conversation_index_kind,
        )
        _ensure_conversation_workspace_metadata(conversation)
        if bound_agent is not None:
            conversation.update(
                {
                    "agent_id": normalized_agent_id,
                    "agentId": normalized_agent_id,
                    "session_role": "workspace",
                    "sessionRole": "workspace",
                }
            )
        else:
            _sync_agent_directory_project_root()
            agent = ensure_agent_for_session(
                session_id,
                display_name=normalized_title,
                llm_bindings=normalized_llm_bindings,
                session_workspace_path=str(conversation.get("workspace_path") or _session_workspace_relative_path(session_id)),
                created_by=created_by,
                conversation_index_kind=conversation_index_kind,
            )
            normalized_agent_id = str(agent.get("agentId") or "").strip()
            if normalized_agent_id:
                conversation["agent_id"] = normalized_agent_id
                conversation["agentId"] = normalized_agent_id
                conversation["session_role"] = "primary"
                conversation["sessionRole"] = "primary"
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    try:
        record_runtime_scene_event(
            "conversation",
            "session_lifecycle",
            "conversation.session.created",
            level="info",
            outcome="succeeded",
            message="Chat session created.",
            fields={
                "sessionId": session_id,
                "agentId": normalized_agent_id,
                "sessionRole": "workspace" if bound_agent is not None else "primary",
                "createdAgent": bound_agent is None,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return get_session_detail(session_id) or {}


def ensure_agent_direct_session(
    *,
    agent_id: str,
    title: str = "",
    created_by: str = "agent_direct_session_repair",
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
) -> dict[str, Any]:
    """Ensure an existing Agent has an ordinary direct chat session."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise SessionValidationError(text_for(get_web_language(), zh="缺少 Agent 绑定。", en="Agent binding is missing."))
    agent = get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise SessionValidationError(_session_agent_unavailable_message("missing_agent", lang=get_web_language()))
    current_session_id = str(agent.get("directSessionId") or "").strip()
    if current_session_id and get_session_detail(current_session_id):
        return get_session_detail(current_session_id) or {}
    lang = get_web_language()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = _now_timestamp()
        session_id = _new_conversation_id(existing_ids)
        display_title = (
            trim_lines(title or "", max_lines=1).strip()
            or str(agent.get("displayName") or "").strip()
            or text_for(lang, zh="Agent 私聊", en="Agent chat")
        )
        conversation = _make_empty_conversation(
            session_id,
            title=display_title,
            timestamp=now,
            conversation_index_kind=conversation_index_kind,
        )
        conversation["created_by"] = str(created_by or "agent_direct_session_repair").strip() or "agent_direct_session_repair"
        conversation["createdBy"] = conversation["created_by"]
        _ensure_conversation_workspace_metadata(conversation)
        _bind_conversation_to_agent_instance(
            conversation,
            agent,
            session_id=session_id,
            source="ensure_agent_direct_session",
            conversation_index_kind=conversation_index_kind,
        )
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    return get_session_detail(session_id) or {}


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


def _bind_conversation_to_agent_instance(
    conversation: dict[str, Any],
    agent: dict[str, Any],
    *,
    session_id: str,
    source: str,
    conversation_index_kind: str = "",
) -> None:
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return
    _release_other_direct_session_agents(session_id, keep_agent_id=agent_id)
    conversation["agent_id"] = agent_id
    conversation["agentId"] = agent_id
    _repair_conversation_agent_legacy_model_fields(
        conversation,
        conversation_id=session_id,
        agent_id=agent_id,
        agent=agent,
    )
    try:
        if str(agent.get("directSessionId") or "").strip() != str(session_id or "").strip():
            update_agent_instance(agent_id, status="active", metadata={"previousDirectSessionId": str(agent.get("directSessionId") or "").strip()})
            agent_directory_service.ensure_agent_for_session(
                session_id,
                display_name=str(agent.get("displayName") or conversation.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE),
                llm_bindings=agent.get("llmBindings") if isinstance(agent.get("llmBindings"), dict) else None,
                primary_mode=str(agent.get("primaryMode") or "chat"),
                role_key=str(agent.get("roleKey") or ""),
                prompt_template_id=str(agent.get("promptTemplateId") or ""),
                existing_agent_id=agent_id,
                session_workspace_path=str(conversation.get("workspace_path") or conversation.get("workspacePath") or _session_workspace_relative_path(session_id)),
                created_by="session_agent_binding",
                conversation_index_kind=conversation_index_kind,
            )
    except AgentNotFoundError:
        raise SessionValidationError(f"Session Agent not found: {agent_id}") from None
    _record_session_agent_binding_updated_event(
        session_id,
        agent_id=agent_id,
        source=source,
        prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
        role_key=str(agent.get("roleKey") or "").strip(),
    )


def _release_other_direct_session_agents(session_id: str, *, keep_agent_id: str) -> None:
    normalized_session_id = str(session_id or "").strip()
    normalized_keep_agent_id = str(keep_agent_id or "").strip()
    if not normalized_session_id or not normalized_keep_agent_id:
        return
    try:
        directory_state = agent_directory_service.load_state()
    except Exception:
        return
    for item in directory_state.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id == normalized_keep_agent_id:
            continue
        if str(item.get("status") or "active").strip().lower() == "archived":
            continue
        if str(item.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        update_agent_instance(
            agent_id,
            direct_session_id="",
            metadata={"previousDirectSessionId": normalized_session_id},
        )


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


def create_chat_review_candidate_from_session(session_id: str) -> dict:
    """Create a pending supervised review candidate from a persisted chat session."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionValidationError(text_for(lang, zh="会话 ID 不能为空。", en="Session id is required."))

    _, conversations = _load_conversations()
    conversation = next(
        (item for item in conversations if str(item.get("id") or "").strip() == conversation_id),
        None,
    )
    if conversation is None:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    stop_requested = _is_session_stop_requested(conversation_id)
    if _is_session_running(conversation_id) or stop_requested:
        _record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="busy",
            level="warning",
            fields={"stopRequested": bool(stop_requested)},
        )
        raise SessionBusyError(
            text_for(
                lang,
                zh="当前会话仍在运行或停止中，结束后再添加到监督评审队列。",
                en="This session is still running or stopping. Add it to review after the turn closes.",
            )
        )

    messages = _session_ledger_visible_messages(conversation_id)
    turns = _build_chat_turn_records_from_messages(messages)
    if len(turns) < 1:
        _record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="no_complete_turn",
            level="warning",
            fields={"messageCount": len(messages), "turnCount": len(turns)},
        )
        raise SessionValidationError(
            text_for(
                lang,
                zh="这个会话还没有完整的用户-助手轮次，不能加入监督评审队列。",
                en="This session does not have a complete user-assistant turn yet.",
            )
        )

    service = ChatDatasetCaptureService(project_root=PROJECT_ROOT)
    try:
        candidate = service.capture_candidate(
            mode="chat",
            session_id=conversation_id,
            source_log_path=_resolve_chat_source_log_path(),
            turns=turns,
            require_auto_capture=False,
            apply_quality_filters=False,
            min_turns=1,
            max_turns=len(turns),
        )
    except Exception as exc:
        _record_session_chat_review_candidate_event(
            "failed",
            session_id=conversation_id,
            outcome="failed",
            level="error",
            fields={
                "messageCount": len(messages),
                "turnCount": len(turns),
                "errorType": exc.__class__.__name__,
            },
        )
        raise

    if candidate is None:
        capture_enabled = bool(getattr(service.config.evolution.chat_dataset, "enabled", False))
        _record_session_chat_review_candidate_event(
            "blocked",
            session_id=conversation_id,
            outcome="duplicate" if capture_enabled else "capture_disabled",
            level="warning",
            fields={"messageCount": len(messages), "turnCount": len(turns)},
        )
        if not capture_enabled:
            raise SessionValidationError(
                text_for(
                    lang,
                    zh="当前配置未启用 chat 数据采集，不能加入监督评审队列。",
                    en="Chat dataset capture is disabled in the current configuration.",
                )
            )
        raise SessionChatReviewCandidateExistsError(
            text_for(
                lang,
                zh="这段会话快照已经生成过监督评审样本，刷新评审工作区即可查看当前状态。",
                en="This session snapshot already has a supervised review sample. Refresh the review workspace to see its current state.",
            )
        )

    _record_session_chat_review_candidate_event(
        "created",
        session_id=conversation_id,
        outcome="created",
        fields={
            "candidateId": candidate.candidate_id,
            "turnCount": candidate.turn_count,
            "qualitySignals": candidate.quality_signals,
            "rawExcerptPath": candidate.raw_excerpt_path,
        },
    )
    return {
        "candidateId": candidate.candidate_id,
        "status": "pending",
        "sessionId": candidate.session_id,
        "topicSummary": candidate.topic_summary,
        "turnCount": candidate.turn_count,
        "qualitySignals": candidate.quality_signals,
        "rawExcerptPath": candidate.raw_excerpt_path,
        "summary": text_for(
            lang,
            zh="已加入监督进化会话评审队列，等待人工判定正例、负例或丢弃。",
            en="Added to the supervised chat review queue for human review.",
        ),
    }


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



def _create_direct_session_submit_kernel_trace(
    conversation: dict[str, Any],
    *,
    agent: dict[str, Any] | None,
    turn_id: str,
    message: str,
    source: str,
) -> dict[str, Any]:
    normalized_source = str(source or "").strip() or "raw"
    if normalized_source in {"agent_inbox", "hot_restart_resume", "supervised_evolution"}:
        return {}
    if not isinstance(conversation, dict) or not isinstance(agent, dict):
        return {}
    session_id = str(conversation.get("id") or conversation.get("conversation_id") or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or agent.get("agentId") or "").strip()
    if not session_id or not normalized_turn_id or not agent_id:
        return {}
    if str(agent.get("agentId") or "").strip() != agent_id:
        return {}
    if str(agent.get("directSessionId") or "").strip() != session_id:
        return {}

    content = str(message or "").strip()
    if not content:
        content = f"Direct session turn {normalized_turn_id}"
    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    event_payload = {
        "eventId": f"session-submit-{session_id}-{normalized_turn_id}",
        "sender": {"type": "user", "id": "session_submit"},
        "recipientAgentIds": [agent_id],
        "semanticType": "agent.session_submit",
        "payload": {
            "goal": f"Direct session turn {normalized_turn_id}",
            "sessionId": session_id,
            "turnId": normalized_turn_id,
            "messageSource": normalized_source,
            "contentLength": len(content),
            "contentHash": content_hash,
        },
        "correlationId": f"session:{session_id}",
        "idempotencyKey": f"session-submit:{session_id}:{normalized_turn_id}",
        "wakeTarget": False,
        "traceOnly": True,
        "metadata": {
            "sourceSurface": "session_submit",
            "sourceSessionId": session_id,
            "sourceMessageId": normalized_turn_id,
            "projectionRef": {"kind": "session_turn", "id": normalized_turn_id},
            "adapterVersion": "session-submit-kernel-bridge-v1",
            "source": normalized_source,
            "targetAgentId": agent_id,
            "agentId": agent_id,
            "messageContentHash": content_hash,
            "messageContentLength": len(content),
        },
    }
    try:
        from core.agent_kernel import service as agent_kernel_service

        if getattr(agent_kernel_service, "PROJECT_ROOT", PROJECT_ROOT) != PROJECT_ROOT:
            agent_kernel_service.PROJECT_ROOT = PROJECT_ROOT
        result = agent_kernel_service.handle_kernel_event(event_payload)
    except Exception as exc:
        trace = {
            "source": "agent_kernel",
            "traceOnly": True,
            "status": "failed",
            "sourceSurface": "session_submit",
            "errorType": type(exc).__name__,
            "reason": trim_lines(str(exc), max_lines=2),
        }
        _record_direct_session_submit_kernel_trace_event(
            conversation,
            trace,
            turn_id=normalized_turn_id,
            agent_id=agent_id,
            source=normalized_source,
            level="warning",
            outcome="failed",
        )
        return trace

    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    outcome_payload = result.get("outcome") if isinstance(result.get("outcome"), dict) else {}
    trace = {
        "source": "agent_kernel",
        "sourceSurface": "session_submit",
        "traceOnly": True,
        "status": "recorded",
        "eventId": str(event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome_payload.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome_payload.get("status") or task.get("status") or "").strip(),
        "reused": bool(result.get("reused")),
    }
    _record_direct_session_submit_kernel_trace_event(
        conversation,
        trace,
        turn_id=normalized_turn_id,
        agent_id=agent_id,
        source=normalized_source,
        outcome=trace["outcomeStatus"] or "succeeded",
    )
    return trace


def _record_direct_session_submit_kernel_trace_event(
    conversation: dict[str, Any],
    kernel_trace: dict[str, Any],
    *,
    turn_id: str,
    agent_id: str,
    source: str,
    level: str = "info",
    outcome: str = "observed",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "kernel",
            (
                "session.submit.kernel_trace_recorded"
                if str(kernel_trace.get("status") or "").strip() == "recorded"
                else "session.submit.kernel_trace_failed"
            ),
            message="Direct Agent session submit Kernel trace.",
            level=level,
            outcome=outcome,
            fields={
                "sessionId": str(conversation.get("id") or conversation.get("conversation_id") or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": str(source or "").strip(),
                "kernelTraceOnly": bool(kernel_trace.get("traceOnly", True)),
                "kernelTraceStatus": str(kernel_trace.get("status") or "").strip(),
                "kernelEventId": str(kernel_trace.get("eventId") or "").strip(),
                "kernelTaskId": str(kernel_trace.get("taskId") or "").strip(),
                "kernelWorkRunId": str(kernel_trace.get("workRunId") or "").strip(),
                "kernelOutcomeId": str(kernel_trace.get("outcomeId") or "").strip(),
                "kernelOutcomeStatus": str(kernel_trace.get("outcomeStatus") or "").strip(),
                "reused": bool(kernel_trace.get("reused")),
                "errorType": str(kernel_trace.get("errorType") or "").strip(),
                "reason": str(kernel_trace.get("reason") or "").strip(),
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


def _repair_agent_direct_session_collisions(
    *,
    source_signature: tuple[Any, ...] | None = None,
) -> bool:
    global _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE
    _sync_agent_directory_project_root()
    signature = source_signature or _session_list_source_signature()
    with _DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        if _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE == signature:
            return False
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        state = agent_directory_service.load_state()
        raw_agents = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
        agents = [item for item in raw_agents if isinstance(item, dict)]
        session_to_agents: dict[str, list[dict[str, Any]]] = {}
        for agent in agents:
            if str(agent.get("status") or "active").strip().lower() == "archived":
                continue
            session_id = str(agent.get("directSessionId") or "").strip()
            agent_id = str(agent.get("agentId") or "").strip()
            if not session_id or not agent_id:
                continue
            session_to_agents.setdefault(session_id, []).append(agent)
        duplicate_groups = {
            session_id: items
            for session_id, items in session_to_agents.items()
            if len(items) > 1
        }
        if not duplicate_groups:
            with _DIRECT_SESSION_COLLISION_REPAIR_LOCK:
                _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = signature
            return False

        existing_session_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict) and str(item.get("conversation_id") or "").strip()
        }
        existing_session_ids.update(
            str(agent.get("directSessionId") or "").strip()
            for agent in agents
            if str(agent.get("directSessionId") or "").strip()
        )
        conversations_by_id = {
            str(item.get("conversation_id") or "").strip(): item
            for item in conversations
            if isinstance(item, dict) and str(item.get("conversation_id") or "").strip()
        }
        now = _now_timestamp()
        repaired: list[dict[str, str]] = []
        preserved_session_ids: set[str] = set()
        for session_id, colliding_agents in sorted(duplicate_groups.items()):
            owner = _select_direct_session_collision_owner(
                session_id,
                colliding_agents,
                conversations_by_id.get(session_id),
            )
            owner_id = str(owner.get("agentId") or "").strip()
            preserved_session_ids.add(session_id)
            conversation = conversations_by_id.get(session_id)
            if conversation is not None and owner_id:
                if conversation.get("agent_id") != owner_id:
                    conversation["agent_id"] = owner_id
                if conversation.get("agentId") != owner_id:
                    conversation["agentId"] = owner_id
            for agent in sorted(colliding_agents, key=_agent_direct_session_collision_repair_sort_key):
                agent_id = str(agent.get("agentId") or "").strip()
                if not agent_id or agent_id == owner_id:
                    continue
                replacement_session_id = _new_conversation_id(existing_session_ids)
                existing_session_ids.add(replacement_session_id)
                previous_metadata = dict(agent.get("metadata") or {})
                metadata = dict(previous_metadata)
                metadata["previousDirectSessionId"] = session_id
                metadata["directSessionCollisionRepairedAt"] = now
                agent["metadata"] = metadata
                agent["directSessionId"] = replacement_session_id
                agent["updatedAt"] = now
                conversation = _agent_directory_conversation_record(agent, session_id=replacement_session_id)
                conversations.append(conversation)
                conversations_by_id[replacement_session_id] = conversation
                repaired.append(
                    {
                        "agentId": agent_id,
                        "agentCode": str(agent.get("agentCode") or "").strip(),
                        "previousSessionId": session_id,
                        "replacementSessionId": replacement_session_id,
                    }
                )
        if not repaired:
            return False
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["updated_at"] = now
        if str(payload.get("active_conversation_id") or "").strip() not in existing_session_ids:
            payload["active_conversation_id"] = str(conversations[0].get("conversation_id") or "").strip() if conversations else ""
        state["agents"] = raw_agents
        agent_directory_service.save_state(state)
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    with _DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = _session_list_source_signature()
    _record_agent_direct_session_collision_repaired_event(
        preserved_session_ids=sorted(preserved_session_ids),
        repaired=repaired,
    )
    return True


def _select_direct_session_collision_owner(
    session_id: str,
    agents: list[dict[str, Any]],
    conversation: dict[str, Any] | None,
) -> dict[str, Any]:
    for agent in agents:
        if (
            str(agent.get("agentId") or "").strip() == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
            and str(session_id or "").strip() == agent_directory_service.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID
        ):
            return agent
    protected_agents = [agent for agent in agents if _agent_direct_session_collision_owner_protected(agent)]
    if protected_agents:
        return sorted(protected_agents, key=_agent_direct_session_collision_owner_sort_key)[0]
    bound_agent_id = str((conversation or {}).get("agent_id") or (conversation or {}).get("agentId") or "").strip()
    if bound_agent_id:
        for agent in agents:
            if str(agent.get("agentId") or "").strip() == bound_agent_id:
                return agent
    direct_match = [
        agent
        for agent in agents
        if str(agent.get("directSessionId") or "").strip() == str(session_id or "").strip()
    ]
    candidates = direct_match or list(agents)
    return sorted(candidates, key=_agent_direct_session_collision_owner_sort_key)[0]


def _agent_direct_session_collision_owner_protected(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    system_role = str(metadata.get("systemRole") or metadata.get("researchOrgRole") or "").strip()
    return bool(metadata.get("protected")) or system_role in {
        "ceo",
        "organization_advisor",
        agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
    }


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


def _agent_directory_stub_hidden_from_user_index(
    agent: dict[str, Any],
    hidden_team_member_agent_ids: set[str],
) -> bool:
    """Hide non-user Agent conversation stubs from the ordinary chat index."""

    classification = agent_directory_service.agent_conversation_index_classification(
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    kind = str(classification.get("kind") or "").strip()
    if kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return True
    agent_id = str(agent.get("agentId") or "").strip()
    if agent_id and agent_id in hidden_team_member_agent_ids:
        visibility = agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        return visibility == agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    return False


def _agent_directory_stub_hidden_team_member_ids() -> set[str]:
    try:
        from . import team_service

        payload = team_service.list_teams_compact(include_archived=False)
    except Exception:
        return set()
    hidden_agent_ids: set[str] = set()
    for team in list((payload or {}).get("teams") or []):
        if not isinstance(team, dict):
            continue
        source = str(team.get("teamSource") or "").strip()
        kind = str(team.get("teamKind") or "").strip()
        if (
            source not in _AGENT_DIRECTORY_STUB_HIDDEN_TEAM_SOURCES
            and kind not in _AGENT_DIRECTORY_STUB_HIDDEN_TEAM_KINDS
        ):
            continue
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if agent_id:
                hidden_agent_ids.add(agent_id)
    return hidden_agent_ids


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


def _ensure_agent_directory_conversation_materialized(
    session_id: str,
    *,
    source: str,
    activate: bool = False,
) -> bool:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        changed = _materialize_agent_directory_conversation_locked(
            payload,
            normalized_session_id,
            source=source,
            activate=activate,
        )
        if changed:
            save_chat_state(PROJECT_ROOT, payload)
        return changed


def _materialize_agent_directory_conversation_locked(
    payload: dict[str, Any],
    session_id: str,
    *,
    source: str,
    activate: bool = False,
) -> bool:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or _find_conversation_entry(payload, normalized_session_id) is not None:
        return False
    agent = _agent_for_direct_session(normalized_session_id)
    if not agent:
        return False
    conversation = _agent_directory_conversation_record(agent, session_id=normalized_session_id)
    if _agent_directory_stub_hidden_from_user_index(agent, _agent_directory_stub_hidden_team_member_ids()):
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        conversations = []
        payload["conversations"] = conversations
    conversations.append(conversation)
    payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
    if activate:
        payload["active_conversation_id"] = normalized_session_id
    payload["updated_at"] = str(conversation.get("updated_at") or _now_timestamp())
    _record_agent_directory_conversation_materialized_event(agent, session_id=normalized_session_id, source=source)
    return True


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


def _agent_directory_conversation_record(agent: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    timestamp = str(agent.get("updatedAt") or agent.get("createdAt") or "").strip() or _now_timestamp()
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
    classification = agent_directory_service.agent_conversation_index_classification(agent)
    conversation = _make_empty_conversation(
        session_id,
        title=display_name,
        timestamp=timestamp,
        conversation_index_kind=str(classification.get("kind") or ""),
    )
    conversation["agent_id"] = str(agent.get("agentId") or "").strip()
    conversation["agentId"] = str(agent.get("agentId") or "").strip()
    _ensure_conversation_workspace_metadata(conversation)
    return conversation


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


def _conversation_agent_deleted_tombstone_matches(conversation: dict[str, Any], *, agent_id: str) -> bool:
    if not isinstance(conversation, dict):
        return False
    normalized_agent_id = str(agent_id or "").strip()
    tombstone = conversation.get("agentDeletedTombstone") if isinstance(conversation.get("agentDeletedTombstone"), dict) else {}
    tombstone_agent_id = str(tombstone.get("agentId") or "").strip()
    deleted_agent_id = str(conversation.get("agentDeletedId") or conversation.get("agent_deleted_id") or "").strip()
    return bool(normalized_agent_id and (tombstone_agent_id == normalized_agent_id or deleted_agent_id == normalized_agent_id))


def _mark_conversation_agent_deleted(
    conversation: dict[str, Any],
    *,
    session_id: str,
    agent_id: str,
    agent_display_name: str,
    previous_status: str,
    hide_from_index: bool = False,
    timestamp: str,
) -> bool:
    changed = False
    deleted_agent_id = str(agent_id or "").strip()
    for key in ("agent_id", "agentId"):
        if conversation.get(key) != "":
            conversation[key] = ""
            changed = True
    for key in ("agent_deleted_id", "agentDeletedId", "agent_missing_id", "agentMissingId"):
        if deleted_agent_id and conversation.get(key) != deleted_agent_id:
            conversation[key] = deleted_agent_id
            changed = True
    display_name = trim_lines(agent_display_name, max_lines=1).strip()
    if display_name and conversation.get("agentDeletedDisplayName") != display_name:
        conversation["agentDeletedDisplayName"] = display_name
        changed = True
    if conversation.get("agentMissing") is not True:
        conversation["agentMissing"] = True
        changed = True
    if conversation.get("agentStatusCode") != "deleted_agent":
        conversation["agentStatusCode"] = "deleted_agent"
        changed = True
    if hide_from_index:
        if conversation.get("hiddenFromIndex") is not True:
            conversation["hiddenFromIndex"] = True
            changed = True
        if conversation.get("conversationIndexKind") != agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
            conversation["conversationIndexKind"] = agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
            changed = True
        if conversation.get("conversationIndexVisibility") != agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN:
            conversation["conversationIndexVisibility"] = agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
            changed = True
    if conversation.get("agentDirectSessionMismatch"):
        conversation["agentDirectSessionMismatch"] = False
        changed = True
    if conversation.get("agentPrimaryDirectSessionId"):
        conversation["agentPrimaryDirectSessionId"] = ""
        changed = True
    next_tombstone = {
        "agentId": deleted_agent_id,
        "sessionId": str(session_id or "").strip(),
        "deletedAt": str(timestamp or "").strip(),
        "previousStatus": str(previous_status or "").strip(),
        "historyRetention": "preserved_tombstone",
    }
    if dict(conversation.get("agentDeletedTombstone") or {}) != next_tombstone:
        conversation["agentDeletedTombstone"] = next_tombstone
        changed = True
    if str(timestamp or "").strip() and conversation.get("updated_at") != timestamp:
        conversation["updated_at"] = timestamp
        changed = True
    return changed


def _agent_directory_conversation_stub(
    agent: dict[str, Any],
    *,
    session_id: str,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
    hidden_team_member_agent_ids = (
        hidden_team_member_agent_ids
        if hidden_team_member_agent_ids is not None
        else _agent_directory_stub_hidden_team_member_ids()
    )
    team_identity = {
        "teamId": str(agent.get("teamId") or "").strip(),
        "teamName": str(agent.get("teamName") or "").strip(),
    }
    classification = agent_directory_service.agent_conversation_index_classification(
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    return {
        "id": session_id,
        "title": display_name,
        "agentId": str(agent.get("agentId") or "").strip(),
        "workspacePath": _session_workspace_relative_path(session_id),
        "messages": [],
        "lastTurnStatus": "",
        "lastTurnError": {},
        "updatedAt": str(agent.get("updatedAt") or agent.get("createdAt") or "").strip(),
        "activeTask": None,
        "conversationIndexVisibility": agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        ),
        "conversationIndexKind": str(classification.get("kind") or "").strip(),
        "conversationIndexErrors": list(classification.get("errors") or []),
        "teamId": team_identity["teamId"],
        "teamName": team_identity["teamName"],
        "_agent": dict(agent),
        "agentDirectoryOnly": True,
    }


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


def _active_chat_turn_work_run_id_for_session(session_id: str) -> str:
    active = _WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return ""
    active_session_id = str(active.get("sessionId") or "").strip()
    if active_session_id and active_session_id != session_id:
        return ""
    return str(active.get("runId") or "").strip()


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


def _persist_session_preflight_rejection(
    conversation: dict[str, Any],
    *,
    message: str,
    reason: str,
    error_type: str,
    http_status: int,
    source: str,
    requested_leases: list[str] | None = None,
    lease_conflicts: list[dict[str, Any]] | None = None,
    lang: str,
) -> dict[str, Any]:
    timestamp = _now_timestamp()
    reason_text = str(reason or "").strip()
    normalized_http_status = _coerce_nonnegative_int(http_status)
    requested = normalize_leases(requested_leases or [])
    conflicts = list(lease_conflicts or [])
    conflict = conflicts[0] if conflicts and isinstance(conflicts[0], dict) else {}
    conflict_run_id = str(conflict.get("runId") or "").strip()
    conflict_leases = normalize_leases(conflict.get("leases") or [])
    message_lines = [
        text_for(
            lang,
            zh="本轮未调用模型：请求在进入 LLM 前被系统拒绝。",
            en="The model was not called: this request was rejected before the LLM stage.",
        ),
        f"HTTP {normalized_http_status}" if normalized_http_status else "",
        reason_text,
    ]
    if conflict_run_id:
        message_lines.append(f"activeRunId: {conflict_run_id}")
    if conflict_leases:
        message_lines.append(f"leases: {', '.join(conflict_leases)}")
    notice_message = "\n".join(line for line in message_lines if str(line or "").strip())
    turn_error = {
        "message": notice_message,
        "error_type": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
        "reason_code": "preflight_rejected",
        "reason_summary": text_for(
            lang,
            zh="请求在进入模型调用前被拒绝",
            en="Request rejected before model call",
        ),
        "reason_detail": reason_text,
        "http_status": normalized_http_status,
        "provider": "",
        "provider_host": "",
        "provider_error_type": "",
        "provider_error_message": "",
        "model": "",
        "recoverable": True,
        "timestamp": timestamp,
        "turn_id": "",
    }
    conversation["runtime_notices"] = _append_session_runtime_notice(
        conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
        {
            "kind": "turn_rejected",
            "level": "warning" if normalized_http_status != 401 else "error",
            "message": notice_message,
            "timestamp": timestamp,
            "source": source,
            "previousStatus": "preflight_rejected",
        },
    )
    conversation["last_cache_composition"] = _not_called_cache_composition(
        recorded_at=timestamp,
        reason="preflight_rejected",
    )
    conversation["last_turn_status"] = "blocked"
    conversation["last_turn_error"] = turn_error
    conversation["updated_at"] = timestamp
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_rejected",
            "conversation.turn.rejected_before_llm",
            level="warning" if normalized_http_status != 401 else "error",
            outcome="rejected",
            message="Conversation turn rejected before any LLM call.",
            fields={
                "sessionId": str(conversation.get("conversation_id") or conversation.get("id") or "").strip(),
                "source": source,
                "httpStatus": normalized_http_status,
                "errorType": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
                "requestedLeases": requested,
                "conflictRunId": conflict_run_id,
                "conflictLeases": conflict_leases,
                "reason": reason_text,
                "userMessageChars": len(str(message or "")),
                "llmCalled": False,
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(str(conversation.get('conversation_id') or conversation.get('id') or '').strip())}-turns.jsonl",
            child_log_payload={
                "event": "turn_rejected_before_llm",
                "timestamp": timestamp,
                "httpStatus": normalized_http_status,
                "errorType": str(error_type or "preflight_rejected").strip() or "preflight_rejected",
                "requestedLeases": requested,
                "conflictRunId": conflict_run_id,
                "conflictLeases": conflict_leases,
                "reason": reason_text,
                "llmCalled": False,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return turn_error


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


def _release_stale_chat_turn_work_run(*, session_id: str, finished_at: str, summary: str) -> None:
    """Clear a persisted active chat_turn when its in-memory worker is gone."""

    active = _WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not isinstance(active, dict):
        return
    active_session_id = str(active.get("sessionId") or "").strip()
    if active_session_id and active_session_id != session_id:
        return
    run_id = str(active.get("runId") or "").strip()
    if not run_id:
        return
    status = str(active.get("status") or active.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=run_id,
        status="stopped",
        summary=summary,
        finished_at=finished_at,
        updated_at=finished_at,
    )
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_recovery",
            "conversation.turn_recovered",
            level="warning",
            outcome="stopped",
            message=summary or "Stale chat turn recovered.",
            fields={
                "sessionId": session_id,
                "turnId": run_id,
                "previousStatus": status,
            },
            lifecycle=True,
        )
    except Exception:
        return


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


def _assistant_timeline_target_indices(items: list[Any], *, source_start_index: int = 1) -> dict[str, int]:
    targets: dict[str, int] = {}
    first_assistant_by_turn: dict[str, int] = {}
    for index, raw in enumerate(list(items or []), start=max(1, int(source_start_index or 1))):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("role") or "").strip().lower() != "assistant":
            continue
        turn_id = _message_turn_id(raw)
        if not turn_id:
            continue
        first_assistant_by_turn.setdefault(turn_id, index)
        content = _sanitize_message_content("assistant", raw.get("content") or "")
        if content:
            targets[turn_id] = index
    for turn_id, index in first_assistant_by_turn.items():
        targets.setdefault(turn_id, index)
    return targets


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


def _complete_turn_error_visible_content(content: Any, metadata: dict[str, Any]) -> str:
    visible = str(content or "").strip()
    reason_summary = str(metadata.get("reasonSummary") or metadata.get("reason_summary") or "").strip()
    reason_detail = str(metadata.get("reasonDetail") or metadata.get("reason_detail") or "").strip()
    http_status = _coerce_nonnegative_int(metadata.get("httpStatus") or metadata.get("http_status"))
    provider_error_type = str(metadata.get("providerErrorType") or metadata.get("provider_error_type") or "").strip()
    provider_error_message = str(metadata.get("providerErrorMessage") or metadata.get("provider_error_message") or "").strip()
    if reason_summary:
        visible = visible.replace("原因：provider 返回了错误。", f"原因：{reason_summary}。")
        visible = visible.replace("Reason: the provider returned an error.", f"Reason: {reason_summary}.")
    if reason_summary and reason_summary not in visible:
        visible = f"{visible} 原因：{reason_summary}。".strip()
    if _provider_error_detail_safe_for_chat(reason_detail) and reason_detail not in visible:
        visible = f"{visible} 具体报错：{reason_detail}。".strip()
    diagnostics: list[str] = []
    if http_status > 0:
        diagnostics.append(f"HTTP {http_status}")
    if provider_error_type:
        diagnostics.append(provider_error_type)
    if (
        _provider_error_detail_safe_for_chat(provider_error_message)
        and provider_error_message not in visible
    ):
        diagnostics.append(provider_error_message)
    if diagnostics:
        diagnostic_line = " / ".join(diagnostics)
        if diagnostic_line not in visible:
            visible = f"{visible} 上游诊断：{diagnostic_line}。".strip()
    return visible


def _provider_error_detail_safe_for_chat(reason_detail: Any) -> bool:
    detail = str(reason_detail or "").strip()
    if not detail:
        return False
    lower = detail.lower()
    if any(marker in lower for marker in ("reasoning_content", "authorization", "bearer ", "api_key", "apikey", "token", "secret")):
        return False
    if "sk-" in lower:
        return False
    return len(detail) <= 180


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


def _normalize_message_attachments(value: Any) -> list[dict[str, Any]]:
    return normalize_chat_attachments(value)


def _normalize_session_references(value: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for raw in list(value or []):
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("sessionId") or raw.get("session_id") or "").strip()
        if not session_id:
            continue
        reference_id = str(raw.get("referenceId") or raw.get("reference_id") or f"session:{session_id}").strip()
        item = {
            "referenceId": reference_id,
            "kind": "session",
            "sessionId": session_id,
            "title": trim_lines(raw.get("title") or session_id, max_lines=1),
            "agentId": str(raw.get("agentId") or raw.get("agent_id") or "").strip(),
            "agentCode": str(raw.get("agentCode") or raw.get("agent_code") or "").strip(),
            "agentDisplayName": trim_lines(raw.get("agentDisplayName") or raw.get("agent_display_name") or "", max_lines=1),
            "summary": trim_lines(raw.get("summary") or "", max_lines=2),
            "createdAt": str(raw.get("createdAt") or raw.get("created_at") or "").strip(),
        }
        if not any(existing.get("referenceId") == item["referenceId"] for existing in references):
            references.append(item)
    return references[:6]


def _resolve_session_references(
    current_session_id: str,
    references: Any,
    *,
    conversations: list[dict[str, Any]],
    lang: str,
) -> list[dict[str, Any]]:
    normalized = _normalize_session_references(references)
    if not normalized:
        return []
    by_id = {
        str(item.get("id") or item.get("conversation_id") or "").strip(): item
        for item in list(conversations or [])
        if isinstance(item, dict) and str(item.get("id") or item.get("conversation_id") or "").strip()
    }
    resolved: list[dict[str, Any]] = []
    for reference in normalized:
        target_id = str(reference.get("sessionId") or "").strip()
        target = by_id.get(target_id)
        if target is None:
            raise SessionValidationError(
                text_for(
                    lang,
                    zh=f"会话引用无效：找不到目标会话 {target_id}。",
                    en=f"Invalid session reference: target session {target_id} was not found.",
                )
            )
        _ensure_conversation_agent_metadata(target)
        agent_id = str(target.get("agent_id") or target.get("agentId") or reference.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        if agent_id and agent is None:
            raise SessionValidationError(
                text_for(
                    lang,
                    zh=f"会话引用无效：目标会话 {target_id} 绑定的 Agent {agent_id} 不存在。",
                    en=f"Invalid session reference: target session {target_id} references missing Agent {agent_id}.",
                )
            )
        if isinstance(agent, dict) and str(agent.get("status") or "").strip() == "archived":
            raise SessionValidationError(
                text_for(
                    lang,
                    zh=f"会话引用无效：目标会话 {target_id} 的 Agent 已归档。",
                    en=f"Invalid session reference: target session {target_id} belongs to an archived Agent.",
                )
            )
        title = trim_lines(reference.get("title") or target.get("title") or target_id, max_lines=1)
        summary = trim_lines(
            reference.get("summary")
            or _latest_message_summary(
                _normalize_messages(
                    target_id,
                    _ledger_visible_messages_for_session(target_id),
                )
            ),
            max_lines=2,
        )
        resolved.append(
            {
                **reference,
                "referenceId": str(reference.get("referenceId") or f"session:{target_id}").strip(),
                "sessionId": target_id,
                "title": title,
                "agentId": agent_id,
                "agentCode": str(target.get("agent_code") or target.get("agentCode") or reference.get("agentCode") or "").strip(),
                "agentDisplayName": trim_lines(
                    target.get("agent_display_name")
                    or target.get("agentDisplayName")
                    or (agent or {}).get("name")
                    or reference.get("agentDisplayName")
                    or "",
                    max_lines=1,
                ),
                "summary": summary,
                "currentSession": target_id == str(current_session_id or "").strip(),
                "permissions": {
                    "query": True,
                    "sendMessage": False,
                    "sendRequiresExplicitUserIntent": True,
                },
            }
        )
    return resolved


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


def _aggregate_session_provider_cache_usage(
    messages: list[dict[str, Any]],
    *,
    fallback_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int]] = set()
    for message in list(messages or []):
        if str((message or {}).get("role") or "").strip().lower() != "assistant":
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        usage = _normalize_turn_llm_usage(metadata.get("llmUsage") or metadata.get("llm_usage"))
        if usage is None or usage.get("source") != "provider_usage":
            continue
        input_tokens = _coerce_nonnegative_int(usage.get("inputTokens") or 0)
        if not input_tokens:
            continue
        key = (
            str(usage.get("recordedAt") or "").strip(),
            input_tokens,
            _coerce_nonnegative_int(usage.get("cachedInputTokens") or 0),
            _coerce_nonnegative_int(usage.get("outputTokens") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        usages.append(usage)
    fallback = _normalize_turn_llm_usage(fallback_usage)
    if fallback is not None and fallback.get("source") == "provider_usage":
        fallback_input = _coerce_nonnegative_int(fallback.get("inputTokens") or 0)
        fallback_key = (
            str(fallback.get("recordedAt") or "").strip(),
            fallback_input,
            _coerce_nonnegative_int(fallback.get("cachedInputTokens") or 0),
            _coerce_nonnegative_int(fallback.get("outputTokens") or 0),
        )
        if fallback_input and fallback_key not in seen:
            usages.append(fallback)
    total_input = sum(_coerce_nonnegative_int(item.get("inputTokens") or 0) for item in usages)
    total_cached = sum(_coerce_nonnegative_int(item.get("cachedInputTokens") or 0) for item in usages)
    total_creation = sum(_coerce_nonnegative_int(item.get("cacheCreationInputTokens") or 0) for item in usages)
    total_uncached = sum(_coerce_nonnegative_int(item.get("uncachedInputTokens") or 0) for item in usages)
    if total_input and not total_uncached:
        total_uncached = max(0, total_input - total_cached)
    return {
        "inputTokens": total_input,
        "cachedInputTokens": min(total_cached, total_input) if total_input else 0,
        "cacheReadInputTokens": min(total_cached, total_input) if total_input else 0,
        "cacheCreationInputTokens": min(total_creation, total_input) if total_input else 0,
        "uncachedInputTokens": min(total_uncached, total_input) if total_input else 0,
        "cacheHitRate": (min(total_cached, total_input) / total_input) if total_input else 0.0,
        "turnCount": len(usages),
    }


def _context_segment_content_preview(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    for key in (
        "contentPreview",
        "content_preview",
        "promptPreview",
        "prompt_preview",
        "content",
    ):
        preview = _compact_preview_text(value.get(key), max_lines=3, max_chars=240)
        if preview:
            return preview
    return ""


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


def _attach_context_segment_content_previews(
    manifest: dict[str, Any] | None,
    previews: dict[str, str],
) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return manifest
    updated = dict(manifest)
    next_segments: list[dict[str, Any]] = []
    for item in list(updated.get("segments") or []):
        if not isinstance(item, dict):
            continue
        segment = dict(item)
        preview = previews.get(str(segment.get("key") or "").strip()) or _context_segment_content_preview(segment)
        if preview:
            segment["contentPreview"] = preview
        next_segments.append(segment)
    updated["segments"] = next_segments
    return updated


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


def _active_chat_turn_work_run_for_session(session_id: str) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    with _RUNNING_SESSIONS_LOCK:
        active_turn_id = str(_SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
    candidates: list[dict[str, Any]] = []
    if active_turn_id:
        snapshot = _WORK_RUN_STORE.load_snapshot("chat_turn", active_turn_id)
        if isinstance(snapshot, dict):
            candidates.append(snapshot)
    active = _WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if isinstance(active, dict):
        candidates.append(active)
    for snapshot in candidates:
        if str(snapshot.get("sessionId") or "").strip() != normalized_session_id:
            continue
        status = str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
        if status in {"queued", "running", "stopping", "paused"}:
            return dict(snapshot)
    return None


def _ordered_model_input_context_segments(context_composition: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context_composition, dict):
        return []
    segments = [
        dict(item)
        for item in list(context_composition.get("segments") or [])
        if isinstance(item, dict) and bool(item.get("includedInModelInput"))
    ]
    if not segments:
        return []
    by_key: dict[str, list[dict[str, Any]]] = {}
    for item in segments:
        key = str(item.get("key") or "").strip()
        if key:
            by_key.setdefault(key, []).append(item)
    ordered: list[dict[str, Any]] = []
    for key in list(context_composition.get("modelInputOrdering") or []):
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        bucket = by_key.get(normalized_key) or []
        if bucket:
            ordered.append(bucket.pop(0))
    used_ids = {id(item) for item in ordered}
    for item in segments:
        if id(item) not in used_ids:
            ordered.append(item)
    return ordered


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


def _estimated_provider_prefix_cache_segments(tokens: int) -> list[dict[str, Any]]:
    normalized_tokens = _coerce_nonnegative_int(tokens)
    if normalized_tokens <= 0:
        return []
    definitions = [
        {
            "key": "system_prompt",
            "label": "system prompt",
            "promptCategory": "system_prompt",
            "weight": 14,
            "description": "Estimated stable system prompt portion inside provider input not mapped by the session manifest.",
            "contentPreview": "系统提示词估算段；原文未展开。",
        },
        {
            "key": "agent_protocol",
            "label": "agent protocol",
            "promptCategory": "agent_spec",
            "weight": 14,
            "description": "Estimated agent behavior/protocol instructions inside provider input not mapped by the session manifest.",
            "contentPreview": "Agent 规范/协议估算段；原文未展开。",
        },
        {
            "key": "tool_descriptions",
            "label": "tool descriptions",
            "promptCategory": "tool_descriptions",
            "weight": 20,
            "description": "Estimated natural-language tool descriptions inside provider input not mapped by the session manifest.",
            "contentPreview": "工具描述估算段；原文未展开。",
        },
        {
            "key": "tool_schema",
            "label": "tool schema",
            "promptCategory": "tool_schema",
            "weight": 42,
            "description": "Estimated provider tool/function schema tokens inside provider input not mapped by the session manifest.",
            "contentPreview": "工具 schema / 函数定义估算段；原文未展开。",
        },
        {
            "key": "provider_unmapped",
            "label": "provider unmapped",
            "promptCategory": "provider_unmapped",
            "weight": 10,
            "description": "Provider input tokens not attributable to a known prompt segment category.",
            "contentPreview": "Provider 输入剩余未映射段；用于提示这里仍是估算边界。",
        },
    ]
    if normalized_tokens < len(definitions):
        definitions = definitions[:normalized_tokens]
    allocations = _weighted_token_allocation(
        normalized_tokens,
        [_coerce_nonnegative_int(item["weight"]) for item in definitions],
    )
    segments: list[dict[str, Any]] = []
    for index, (definition, allocation) in enumerate(zip(definitions, allocations), start=0):
        token_count = _coerce_nonnegative_int(allocation)
        if token_count <= 0:
            continue
        segments.append(
            {
                "key": str(definition["key"]),
                "label": str(definition["label"]),
                "tokens": token_count,
                "status": "computed_hit",
                "source": "provider_input_remainder",
                "description": str(definition["description"]),
                "cachePolicy": "assumed_stable_prefix",
                "order": index,
                "contentPreview": str(definition["contentPreview"]),
                "promptCategory": str(definition["promptCategory"]),
                "segmentKind": "prompt_source",
                "accuracy": "estimated",
                "parentKey": "provider_input_remainder",
                "estimated": True,
            }
        )
    return segments


def _provider_cache_calibration_reason(
    *,
    provider: str,
    model: str,
    source: str,
    cache_creation_tokens: int,
    overestimated_tokens: int,
    provider_extra_cached_tokens: int,
) -> tuple[str, str]:
    provider_name = provider.lower()
    model_name = model.lower()
    if source != "provider_usage":
        return (
            "not_available",
            "Provider cache usage was not returned; computed segments are shown as theoretical cache candidates.",
        )
    if overestimated_tokens > 0:
        if "xiaomi" in provider_name or "mimo" in model_name:
            if cache_creation_tokens <= 0:
                return (
                    "provider_lower_than_computed",
                    "Xiaomi/MiMo returned fewer cache-read tokens than the computed stable-prefix upper bound and reported no new cache creation for this turn.",
                )
            return (
                "provider_lower_than_computed",
                "Xiaomi/MiMo returned fewer cache-read tokens than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        if "qwen" in provider_name or "qwen" in model_name:
            return (
                "provider_lower_than_computed",
                "Qwen provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        if "openai" in provider_name or "gpt" in model_name:
            return (
                "provider_lower_than_computed",
                "OpenAI provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
            )
        return (
            "provider_lower_than_computed",
            "Provider cache usage is lower than the computed stable-prefix upper bound; the difference is attributed to computed prefix segments.",
        )
    if provider_extra_cached_tokens > 0:
        return (
            "provider_higher_than_computed",
            "Provider reported more cached input than the context manifest can map to computed cacheable segments.",
        )
    return (
        "aligned",
        "Provider cache usage matches the computed stable-prefix upper bound for mapped input tokens.",
    )


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


def _estimate_context_segment_tokens(chars: int, item_count: int = 0) -> int:
    return max(0, int((max(0, chars) + 2) // 3) + max(0, item_count) * 8)


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


def _context_segment(
    key: str,
    label: str,
    *,
    content: Any = None,
    chars: int = 0,
    tokens: int = 0,
    item_count: int = 0,
    status: str = "included",
    source: str = "",
    description: str = "",
    kind: str = "",
    lifecycle: str = "",
    authority: int = 0,
    volatility: int = 0,
    relevance: int = 0,
    placement: str = "",
    cache_policy: str = "",
    retention: str = "",
    included_in_model_input: bool = True,
    evidence_ref: str = "",
    content_hash: str = "",
    stale: bool = False,
) -> dict[str, Any]:
    return build_context_segment(
        key,
        label,
        content=content,
        chars=chars,
        tokens=tokens,
        item_count=item_count,
        status=status,
        source=source,
        description=description,
        kind=kind,
        lifecycle=lifecycle,
        authority=authority,
        volatility=volatility,
        relevance=relevance,
        placement=placement,
        cache_policy=cache_policy,
        retention=retention,
        included_in_model_input=included_in_model_input,
        evidence_ref=evidence_ref,
        content_hash=content_hash,
        stale=stale,
    )


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


def _agent_context_segment_label(key: str) -> str:
    normalized = str(key or "").strip()
    return _AGENT_CONTEXT_SEGMENT_LABELS.get(normalized, normalized.replace("_", " ") or "agent context")


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


def _conversation_agent_dialogue_context_window(cfg: Any, conversation: dict[str, Any] | None) -> int:
    return _coerce_nonnegative_int(_conversation_agent_dialogue_context_window_payload(cfg, conversation).get("limit") or 0)


def _conversation_agent_dialogue_context_window_payload(cfg: Any, conversation: dict[str, Any] | None) -> dict[str, Any]:
    agent = _conversation_agent_for_context_limit(conversation)
    agent_id = str((agent or {}).get("agentId") or "").strip() if isinstance(agent, dict) else ""
    model_id = agent_dialogue_model_id(agent)
    if not model_id:
        return {"limit": 0, "modelId": "", "agentId": agent_id}
    try:
        entry = getattr(cfg.llm, "model_library", {}).get(model_id)
    except Exception:
        entry = None
    if not isinstance(entry, dict):
        return {"limit": 0, "modelId": model_id, "agentId": agent_id}
    explicit_limit = _first_positive_int(
        entry.get("context_window"),
        entry.get("contextWindow"),
        entry.get("max_model_len"),
        entry.get("context_length"),
    )
    if explicit_limit:
        return {"limit": explicit_limit, "modelId": model_id, "agentId": agent_id}
    provider_id = str(entry.get("provider_id") or "").strip()
    if not provider_id:
        return {"limit": 0, "modelId": model_id, "agentId": agent_id}
    try:
        provider = cfg.llm.get_provider(provider_id)
        return {
            "limit": int(getattr(provider, "context_window", 0) or 0),
            "modelId": model_id,
            "agentId": agent_id,
        }
    except Exception:
        return {"limit": 0, "modelId": model_id, "agentId": agent_id}


def _conversation_agent_for_context_limit(conversation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(conversation, dict):
        return None
    cached_agent = conversation.get("_agent")
    if isinstance(cached_agent, dict):
        return cached_agent
    agent_id = str(conversation.get("agentId") or conversation.get("agent_id") or "").strip()
    if not agent_id:
        return None
    return get_agent(agent_id)


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


def _find_conversation_entry(payload: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() == session_id:
            return item
    return None


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


def _new_conversation_id(existing_ids: set[str] | None = None) -> str:
    existing = set(existing_ids or set())
    base = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


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


def _make_empty_conversation(
    session_id: str,
    *,
    title: str,
    timestamp: str,
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT,
) -> dict[str, Any]:
    normalized_index_kind = agent_directory_service.normalize_conversation_index_kind(conversation_index_kind)
    if not normalized_index_kind:
        normalized_index_kind = agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
    normalized_index_visibility = _conversation_index_visibility_for_kind(normalized_index_kind)
    conversation = {
        "conversation_id": str(session_id or "").strip(),
        "title": str(title or "").strip() or DEFAULT_CHAT_CONVERSATION_TITLE,
        "workspace_path": _session_workspace_relative_path(session_id),
        "updated_at": str(timestamp or "").strip() or _now_timestamp(),
        "last_turn_status": "ready",
        "last_turn_error": None,
        "active_task": None,
        "conversation_index_kind": normalized_index_kind,
        "conversationIndexKind": normalized_index_kind,
        "conversation_index_visibility": normalized_index_visibility,
        "conversationIndexVisibility": normalized_index_visibility,
    }
    if normalized_index_kind == agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    return conversation


def _normalize_session_agent_llm_bindings(value: Any) -> dict[str, dict[str, str]]:
    normalized = agent_directory_service.normalize_agent_llm_bindings(value)
    if agent_dialogue_model_id({"llmBindings": normalized}):
        return normalized
    default_model_id = _default_session_dialogue_model_id()
    if default_model_id:
        normalized["dialogue"] = {"modelId": default_model_id}
    return normalized


def default_session_llm_bindings() -> dict[str, dict[str, str]]:
    return _normalize_session_agent_llm_bindings(None)


def _session_agent_reasoning_effort(agent: dict[str, Any] | None, slot: str = SESSION_LLM_SLOT_DIALOGUE) -> str:
    metadata = agent.get("metadata") if isinstance(agent, dict) and isinstance(agent.get("metadata"), dict) else {}
    by_slot = metadata.get("llmReasoningEffort") if isinstance(metadata.get("llmReasoningEffort"), dict) else {}
    return str(by_slot.get(slot) or "").strip().lower()


def _session_llm_model_choices() -> list[dict[str, Any]]:
    from .agent_model_candidate_service import list_agent_model_candidates

    default_model_id = _default_session_dialogue_model_id()
    choices = copy.deepcopy(list_agent_model_candidates().get("candidates") or [])
    for choice in choices:
        choice["isDefault"] = str(choice.get("modelId") or "").strip() == default_model_id
        values = [
            str(value or "").strip().lower()
            for value in list(choice.get("reasoningEffortValues") or [])
            if str(value or "").strip()
        ]
        choice["reasoningEffortValues"] = values
        provided_options = choice.get("reasoningEffortOptions") if isinstance(choice.get("reasoningEffortOptions"), list) else []
        option_by_value = {
            str(item.get("value") or "").strip().lower(): item
            for item in provided_options
            if isinstance(item, dict) and str(item.get("value") or "").strip()
        }
        choice["reasoningEffortOptions"] = [
            {
                "value": value,
                "label": str((option_by_value.get(value) or {}).get("label") or {
                    "low": "低",
                    "medium": "中",
                    "high": "高",
                }.get(value, value)).strip(),
                "description": str((option_by_value.get(value) or {}).get("description") or {
                    "low": "更快响应，适合直接问题",
                    "medium": "平衡速度与推理深度",
                    "high": "更深推理，适合复杂任务",
                }.get(value, "")).strip(),
            }
            for value in values
        ]
        requested_default = str(choice.get("defaultReasoningEffort") or "").strip().lower()
        choice["defaultReasoningEffort"] = requested_default if requested_default in values else "medium" if "medium" in values else (values[0] if values else "")
    return choices


def _session_agent_id_snapshot(session_id: str) -> str:
    normalized_session_id = str(session_id or "").strip()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise SessionNotFoundError(f"Session not found: {normalized_session_id}")
        return str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()


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


def get_session_llm_options(session_id: str) -> dict[str, Any]:
    current_reasoning_effort = _session_reasoning_effort_snapshot(session_id)
    model = _session_fixed_model_choice(session_id)
    return {
        "sessionId": str(session_id or "").strip(),
        "currentModelId": str(model.get("modelRef") or model.get("modelId") or "").strip(),
        "currentReasoningEffort": normalize_reasoning_effort(current_reasoning_effort),
        "model": model,
    }


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


def _normalize_session_agent_profile_id(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized or DEFAULT_SESSION_AGENT_PROFILE_ID


def llm_bindings_for_profile_id(profile_id: Any) -> dict[str, dict[str, str]]:
    normalized_profile_id = _normalize_session_agent_profile_id(profile_id)
    try:
        config = get_config()
        profile = config.llm.get_profile(profile_id=normalized_profile_id)
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
    except Exception:
        model_id = ""
    normalized = {"dialogue": {"modelId": str(model_id or "").strip()}} if str(model_id or "").strip() else {}
    return _normalize_session_agent_llm_bindings(normalized)


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


def _session_agent_config_for_llm_bindings(agent_instance: dict[str, Any] | None) -> Any:
    return _session_agent_config_for_llm_slot(agent_instance, SESSION_LLM_SLOT_DIALOGUE)


def _resolve_session_agent_llm(
    agent_instance: dict[str, Any] | None,
    llm_slot: str,
    *,
    reasoning_effort: str | None = None,
) -> Any:
    normalized_slot = str(llm_slot or "").strip() or SESSION_LLM_SLOT_DIALOGUE
    try:
        return resolve_agent_llm(
            agent_instance,
            normalized_slot,
            config=get_config(),
            runtime_profile_id=DEFAULT_SESSION_AGENT_PROFILE_ID,
            fallback_to_dialogue=normalized_slot != SESSION_LLM_SLOT_DIALOGUE,
            reasoning_effort_override=reasoning_effort,
        )
    except AgentLlmResolutionError as exc:
        raise SessionValidationError(str(exc)) from exc


def _session_agent_config_for_llm_slot(agent_instance: dict[str, Any] | None, llm_slot: str) -> Any:
    return _resolve_session_agent_llm(agent_instance, llm_slot).config


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


def _agent_prompt_snapshot_matches_agent(
    snapshot: Any,
    *,
    agent_id: str,
    prompt_template_id: str,
    builtin_content_version: int = 0,
    chat_base_prompt_version: int = 0,
) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if str(snapshot.get("reason") or "").strip():
        return False
    if str(snapshot.get("agentId") or "").strip() != str(agent_id or "").strip():
        return False
    if str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip() != str(prompt_template_id or "").strip():
        return False
    try:
        snapshot_builtin_content_version = max(0, int(snapshot.get("builtinContentVersion") or 0))
    except (TypeError, ValueError):
        snapshot_builtin_content_version = 0
    try:
        snapshot_chat_base_prompt_version = max(0, int(snapshot.get("chatBasePromptVersion") or 0))
    except (TypeError, ValueError):
        snapshot_chat_base_prompt_version = 0
    return (
        max(0, int(builtin_content_version or 0)) <= snapshot_builtin_content_version
        and max(0, int(chat_base_prompt_version or 0)) <= snapshot_chat_base_prompt_version
    )


def _ensure_session_agent_prompt_snapshot(
    session_id: str,
    agent: dict[str, Any] | None,
    *,
    snapshot_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or not isinstance(agent, dict):
        return {}
    agent_id = str(agent.get("agentId") or "").strip()
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    if not agent_id or not prompt_template_id:
        return {}
    include_chat_base = str(agent.get("primaryMode") or "").strip().lower() == "chat"
    required_versions = prompt_template_service.get_agent_prompt_snapshot_versions(
        prompt_template_id,
        project_root=PROJECT_ROOT,
        include_chat_base=include_chat_base,
    )
    if _agent_prompt_snapshot_matches_agent(
        snapshot_hint,
        agent_id=agent_id,
        prompt_template_id=prompt_template_id,
        builtin_content_version=required_versions.get("builtinContentVersion", 0),
        chat_base_prompt_version=required_versions.get("chatBasePromptVersion", 0),
    ):
        _record_session_prompt_snapshot_event(
            normalized_session_id,
            agent_id=agent_id,
            snapshot=snapshot_hint,
            outcome="reused",
        )
        return dict(snapshot_hint)
    with _CHAT_STATE_LOCK, chat_state_transaction(PROJECT_ROOT):
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return {}
        existing = conversation.get("agentPromptSnapshot")
        if _agent_prompt_snapshot_matches_agent(
            existing,
            agent_id=agent_id,
            prompt_template_id=prompt_template_id,
            builtin_content_version=required_versions.get("builtinContentVersion", 0),
            chat_base_prompt_version=required_versions.get("chatBasePromptVersion", 0),
        ):
            _record_session_prompt_snapshot_event(
                normalized_session_id,
                agent_id=agent_id,
                snapshot=existing,
                outcome="reused",
            )
            return dict(existing)
        snapshot = prompt_template_service.build_agent_prompt_snapshot(
            prompt_template_id,
            agent_id=agent_id,
            agent_code=str(agent.get("agentCode") or "").strip(),
            agent_display_name=str(agent.get("displayName") or "").strip(),
            project_root=PROJECT_ROOT,
            include_chat_base=include_chat_base,
        )
        if str(snapshot.get("reason") or "").strip():
            _record_session_prompt_snapshot_event(
                normalized_session_id,
                agent_id=agent_id,
                snapshot=snapshot,
                outcome="failed",
            )
            return dict(snapshot)
        conversation["agentPromptSnapshot"] = dict(snapshot)
        payload["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
        _record_session_prompt_snapshot_event(
            normalized_session_id,
            agent_id=agent_id,
            snapshot=snapshot,
            outcome="refreshed" if isinstance(existing, dict) else "created",
        )
        return dict(snapshot)


def _render_agent_prompt_snapshot_block(snapshot: Any) -> str:
    return prompt_template_service.render_agent_prompt_snapshot_system_block(snapshot if isinstance(snapshot, dict) else None)


def _prompt_snapshot_context_segment(snapshot_block: str, snapshot: Any) -> dict[str, Any] | None:
    text = str(snapshot_block or "").strip()
    if not text:
        return None
    return {
        "key": "agent_prompt_snapshot",
        "block": text,
        "placement": "cache_prefix",
        "stability": "session_static",
        "chars": len(text),
        "hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
        "promptTemplateId": str((snapshot or {}).get("promptTemplateId") or "").strip() if isinstance(snapshot, dict) else "",
        "contentHash": str((snapshot or {}).get("contentHash") or "").strip() if isinstance(snapshot, dict) else "",
    }


def _session_context_segments_block(segments: Any, placement: str) -> str:
    normalized_placement = str(placement or "").strip()
    return "\n\n".join(
        str(item.get("block") or "").strip()
        for item in list(segments or [])
        if isinstance(item, dict)
        and str(item.get("placement") or "").strip() == normalized_placement
        and str(item.get("block") or "").strip()
    ).strip()


def _session_context_segments_without_prompt_template(segments: Any) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in list(segments or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("key") or "").strip() == "prompt_template":
            continue
        filtered.append(dict(item))
    return filtered


def _record_session_prompt_snapshot_event(
    session_id: str,
    *,
    agent_id: str,
    snapshot: dict[str, Any],
    outcome: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "prompt_snapshot",
            f"session.prompt_snapshot.{str(outcome or 'observed').strip() or 'observed'}",
            level="warning" if outcome == "failed" else "info",
            outcome=str(outcome or "observed").strip() or "observed",
            message="Session Agent prompt snapshot state changed.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "promptTemplateId": str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip(),
                "contentHash": str(snapshot.get("contentHash") or "").strip(),
                "contentLength": int(snapshot.get("contentLength") or len(str(snapshot.get("content") or ""))),
                "category": str(snapshot.get("category") or "").strip(),
                "reason": str(snapshot.get("reason") or "").strip(),
                "source": "session_service",
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-prompt-snapshots.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "agent_id": str(agent_id or "").strip(),
                "prompt_template_id": str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip(),
                "content_hash": str(snapshot.get("contentHash") or "").strip(),
                "content_length": int(snapshot.get("contentLength") or len(str(snapshot.get("content") or ""))),
                "category": str(snapshot.get("category") or "").strip(),
                "reason": str(snapshot.get("reason") or "").strip(),
                "outcome": str(outcome or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


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


def list_active_session_work_runs() -> list[dict[str, Any]]:
    """Return active web chat turns as lightweight WorkRun lease snapshots."""

    with _RUNNING_SESSIONS_LOCK:
        session_ids = sorted(_RUNNING_SESSION_IDS)
        active_turn_ids = dict(_SESSION_ACTIVE_TURN_IDS)
        active_leases = {key: list(value) for key, value in _SESSION_ACTIVE_TURN_LEASES.items()}
    active_statuses = _active_session_work_run_statuses(session_ids)
    return [
        {
            "runId": active_turn_ids.get(session_id) or f"chat-turn-{session_id}",
            "runKind": "chat_turn",
            "sessionId": session_id,
            "status": active_statuses.get(session_id) or "running",
            "currentPhase": active_statuses.get(session_id) or "running",
            "leases": active_leases.get(session_id) or ["readonly_chat"],
        }
        for session_id in session_ids
    ]


def _active_session_work_run_statuses(session_ids: list[str]) -> dict[str, str]:
    if not session_ids:
        return {}
    session_id_set = set(session_ids)
    statuses: dict[str, str] = {}
    try:
        with _CHAT_STATE_LOCK:
            payload = load_chat_state(PROJECT_ROOT)
            conversations = payload.get("conversations") if isinstance(payload, dict) else []
            for conversation in conversations if isinstance(conversations, list) else []:
                if not isinstance(conversation, dict):
                    continue
                session_id = str(conversation.get("conversation_id") or "").strip()
                if session_id not in session_id_set:
                    continue
                status = str(
                    conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or ""
                ).strip().lower()
                if status in {"queued", "running", "stopping"}:
                    statuses[session_id] = status
    except Exception:
        return {}
    return statuses


def active_session_has_write_leases() -> bool:
    for run in list_active_session_work_runs():
        leases = set(leases_for_snapshot(run))
        if leases.intersection({WORKTREE_WRITE_LEASE, MEMORY_WRITE_LEASE}):
            return True
    return False


def load_chat_turn_work_run_summary() -> dict[str, Any]:
    active_items = list_active_session_work_runs()
    active = _WORK_RUN_STORE.load_active_snapshot("chat_turn")
    if not active and active_items:
        active = active_items[0]
    return {
        "active": active,
        "activeItems": active_items,
        "latest": _WORK_RUN_STORE.load_latest_snapshot("chat_turn"),
    }


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


def _matches_attachment_reference_pattern(normalized: str, pattern: str) -> bool:
    if not pattern:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 _'-]*", pattern):
        return re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", normalized) is not None
    return pattern in normalized


def _contains_any_attachment_reference_pattern(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches_attachment_reference_pattern(normalized, pattern) for pattern in patterns)


def _resolve_image_attachment_capability(
    *,
    agent_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supports_image_input = _session_agent_supports_image_input(
        agent_instance,
        slot=SESSION_LLM_SLOT_DIALOGUE,
    )
    model_id = _session_agent_llm_slot_model_id(agent_instance, SESSION_LLM_SLOT_DIALOGUE)
    model_name = _session_agent_llm_model_name(
        agent_instance,
        slot=SESSION_LLM_SLOT_DIALOGUE,
    )
    return {
        "supports_image_input": supports_image_input,
        "model_name": model_name,
        "model_id": model_id,
        "llm_slot": SESSION_LLM_SLOT_DIALOGUE,
    }


def _session_agent_supports_image_input(
    agent_instance: dict[str, Any] | None,
    *,
    slot: str = SESSION_LLM_SLOT_DIALOGUE,
) -> bool | None:
    model_id = _session_agent_llm_slot_model_id(agent_instance, slot)
    if not model_id:
        return None
    try:
        config = get_config()
        resolved = resolve_agent_llm(
            agent_instance,
            slot,
            config=config,
            fallback_to_dialogue=slot != SESSION_LLM_SLOT_DIALOGUE,
        )
        capability_records = (
            resolved.resolved_spec.provider_details.get("capabilities", {})
            if resolved.resolved_spec is not None
            and isinstance(resolved.resolved_spec.provider_details, dict)
            else {}
        )
        image_input_record = (
            capability_records.get("image_input")
            if isinstance(capability_records, dict)
            else None
        )
        if isinstance(image_input_record, dict):
            capability_value = str(image_input_record.get("value") or "").strip().lower()
            if capability_value == "supported":
                return True
            if capability_value == "unsupported":
                return False
            if capability_value == "unknown":
                return None
        if resolved.capabilities is not None:
            supports_image_input = resolved.capabilities.supports_image_input
            return supports_image_input if isinstance(supports_image_input, bool) else None
        llm_config = config.llm
    except Exception:
        try:
            llm_config = get_config().llm
        except Exception:
            return None
    entry = llm_config.model_library.get(model_id)
    if not isinstance(entry, dict):
        return None
    provider_id = str(entry.get("provider_id") or "").strip()
    try:
        provider = llm_config.get_provider(provider_id)
        lowered_provider = str(getattr(provider, "kind", "") or "").strip().lower()
    except Exception:
        lowered_provider = ""
    return model_record_image_input_support(entry, provider_kind=lowered_provider)


def _session_agent_dialogue_model_name(agent_instance: dict[str, Any] | None) -> str:
    return _session_agent_llm_model_name(agent_instance, slot=SESSION_LLM_SLOT_DIALOGUE)


def _session_agent_llm_slot_model_id(agent_instance: dict[str, Any] | None, slot: str) -> str:
    normalized_slot = str(slot or "").strip() or SESSION_LLM_SLOT_DIALOGUE
    return agent_llm_model_id(
        agent_instance,
        normalized_slot,
        fallback_to_dialogue=normalized_slot != SESSION_LLM_SLOT_DIALOGUE,
    )


def _session_agent_llm_model_name(agent_instance: dict[str, Any] | None, *, slot: str = SESSION_LLM_SLOT_DIALOGUE) -> str:
    model_id = _session_agent_llm_slot_model_id(agent_instance, slot)
    if not model_id:
        return ""
    try:
        entry = get_config().llm.model_library.get(model_id)
    except Exception:
        return ""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("model") or entry.get("label") or model_id).strip()


def _recent_image_attachment_missing_message(lang: str) -> str:
    return text_for(
        lang,
        zh="我没有在当前会话里找到可重新查看的最近图片附件。请重新发送图片，或在消息里附上要我查看的图片。",
        en="I could not find a recent image attachment in this session to inspect again. Please attach or resend the image.",
    )


def _image_input_unsupported_message(lang: str, *, model_name: str = "") -> str:
    model_label = str(model_name or "").strip() or text_for(lang, zh="当前模型", en="current model")
    return text_for(
        lang,
        zh=f"当前 Agent 使用的对话模型 `{model_label}` 明确不支持图像输入，所以我没有把图片发送给模型。请在 Agent 管理中切换到支持图像输入的对话模型；需要生成/调整图片时，由对话模型理解上下文后再按工具协议调用 image2 工具。",
        en=f"The current Agent dialogue model `{model_label}` does not support image input, so I did not send the image to the model. Switch this Agent to a vision-capable dialogue model; image generation/editing should be invoked by the dialogue model through the image2 tool protocol after it understands the context.",
    )


def _finish_image_attachment_preflight_turn(
    session_id: str,
    turn_id: str,
    result: dict[str, Any],
    *,
    decision: str,
    reason: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    leases: list[str] | None,
    raw_user_message: str,
    outcome: str = "completed",
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    _record_image_attachment_capability_event(
        session_id,
        turn_id=turn_id,
        decision=decision,
        reason=reason,
        outcome=outcome,
        level=level,
        agent_id=agent_id,
        attachments=attachments,
        fields={
            **(fields or {}),
            "resultStatus": str(result.get("status") or "").strip(),
            "assistantTextLength": len(str(result.get("summary") or result.get("raw_output") or "")),
        },
    )
    _persist_session_turn_result(session_id, result, turn_id=turn_id)
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status=_chat_turn_result_status(str(result.get("status") or "completed"), result, stop_requested=False),
        agent_id=agent_id,
        leases=leases,
        user_message=raw_user_message,
        summary=str(result.get("summary") or result.get("raw_output") or "").strip(),
        finished_at=_now_timestamp(),
    )
    _set_session_running(session_id, False, turn_id=turn_id)
    _clear_session_turn_control(session_id, turn_id=turn_id)
    _publish_session_detail_snapshot(session_id)


def _record_image_attachment_capability_event(
    session_id: str,
    *,
    turn_id: str,
    decision: str,
    reason: str,
    outcome: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "image_attachment_capability",
            "conversation.image_attachment.capability_checked",
            level=level,
            outcome=outcome,
            message="Image input capability checked without semantic intent routing.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "decision": str(decision or "").strip(),
                "reason": str(reason or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "attachmentCount": len(_normalize_message_attachments(attachments or [])),
                "attachments": _safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-image-capability.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                "decision": str(decision or "").strip(),
                "reason": str(reason or "").strip(),
                "agent_id": str(agent_id or "").strip(),
                "attachment_count": len(_normalize_message_attachments(attachments or [])),
                "attachments": _safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene image attachment capability log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _persist_chat_turn_work_run(
    *,
    session_id: str,
    turn_id: str,
    status: str,
    agent_id: str = "",
    leases: list[str] | None = None,
    user_message: str = "",
    summary: str = "",
    error_type: str = "",
    error: str = "",
    started_at: str = "",
    updated_at: str = "",
    finished_at: str = "",
    last_tool_error: dict[str, Any] | None = None,
) -> None:
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return
    now = _now_timestamp()
    previous = _WORK_RUN_STORE.load_snapshot("chat_turn", normalized_turn_id) or {}
    started = str(started_at or previous.get("startedAt") or now).strip()
    finished = str(finished_at or previous.get("finishedAt") or "").strip()
    normalized_status = str(status or previous.get("status") or "running").strip().lower() or "running"
    if normalized_status in {"running", "stopping"}:
        active_run_id = normalized_turn_id
    elif normalized_status == "queued":
        active_run_id = _replacement_active_chat_turn_id(exclude_turn_id=normalized_turn_id) or normalized_turn_id
    else:
        active_run_id = _replacement_active_chat_turn_id(exclude_turn_id=normalized_turn_id)
    payload = {
        **previous,
        "runId": normalized_turn_id,
        "runKind": "chat_turn",
        "track": "dialogue",
        "sessionId": str(session_id or previous.get("sessionId") or "").strip(),
        "agentId": str(agent_id or previous.get("agentId") or "").strip(),
        "status": normalized_status,
        "currentPhase": normalized_status,
        "leases": list(leases or previous.get("leases") or ["readonly_chat"]),
        "userMessage": str(user_message or previous.get("userMessage") or "").strip(),
        "summary": str(summary or previous.get("summary") or "").strip(),
        "errorType": str(error_type or previous.get("errorType") or "").strip(),
        "error": str(error or previous.get("error") or "").strip(),
        "startedAt": started,
        "updatedAt": str(updated_at or now).strip(),
        "finishedAt": finished
        if normalized_status
        in {
            "completed",
            "failed",
            "failed_provider",
            "failed_runtime",
            "stopped",
            "cancelled",
            "paused_limit",
            "needs_continue",
            "stopped_by_user",
            "superseded",
        }
        else "",
    }
    if isinstance(last_tool_error, dict) and last_tool_error:
        payload["lastToolError"] = {
            "toolName": trim_lines(str(last_tool_error.get("toolName") or ""), max_lines=1),
            "summary": trim_lines(str(last_tool_error.get("summary") or ""), max_lines=2),
            "errorPreview": trim_lines(str(last_tool_error.get("errorPreview") or ""), max_lines=2),
            "relatedEventCode": trim_lines(str(last_tool_error.get("relatedEventCode") or ""), max_lines=1),
            "updatedAt": str(last_tool_error.get("updatedAt") or now).strip(),
        }
    _WORK_RUN_STORE.persist_snapshot("chat_turn", payload, active_run_id=active_run_id)


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


def _reconcile_source_collection_stage_task_after_turn(
    metadata: dict[str, str],
    *,
    session_id: str,
    turn_id: str,
    final_status: str,
) -> None:
    if not isinstance(metadata, dict) or not metadata:
        return
    team_id = str(metadata.get("teamId") or "").strip()
    task_id = str(metadata.get("taskId") or "").strip()
    if not team_id or not task_id:
        return
    try:
        from core.web.services import team_workflow_orchestration_service

        result = team_workflow_orchestration_service.reconcile_source_collection_stage_session_task_after_turn(
            team_id,
            task_id,
            run_id=str(metadata.get("runId") or "").strip(),
            session_id=session_id,
            turn_id=turn_id,
            reason=f"session_turn_{final_status or 'completed'}",
        )
    except Exception as exc:  # pragma: no cover - defensive, session persistence must not fail here
        _record_session_turn_lifecycle_event(
            session_id,
            "source_collection_stage_task_reconcile_failed",
            turn_id=turn_id,
            level="warning",
            outcome="failed",
            fields={
                "teamId": team_id,
                "taskId": task_id,
                "runId": str(metadata.get("runId") or "").strip(),
                "finalStatus": str(final_status or "").strip(),
                "errorType": type(exc).__name__,
                "error": trim_lines(str(exc), max_lines=2),
            },
        )
        return
    if not isinstance(result, dict) or not bool(result.get("changed")):
        return
    _record_session_turn_lifecycle_event(
        session_id,
        "source_collection_stage_task_reconciled",
        turn_id=turn_id,
        outcome=str(result.get("taskStatus") or "reconciled").strip() or "reconciled",
        fields={
            "teamId": team_id,
            "runId": str(result.get("runId") or metadata.get("runId") or "").strip(),
            "taskId": task_id,
            "stageId": str(metadata.get("stageId") or "").strip(),
            "agentId": str(metadata.get("agentId") or "").strip(),
            "agentRole": str(metadata.get("agentRole") or "").strip(),
            "finalStatus": str(final_status or "").strip(),
            "previousTaskStatus": str(result.get("previousTaskStatus") or "").strip(),
            "taskStatus": str(result.get("taskStatus") or "").strip(),
            "completionGatePassed": bool(result.get("completionGatePassed")),
            "taskChecklistComplete": bool(result.get("taskChecklistComplete")),
            "artifactComplete": bool(result.get("artifactComplete")),
        },
    )


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






def _session_agent_runtime_cache_fingerprint(
    *,
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str,
    resolved_llm: Any | None,
    mode: str,
    prompt_snapshot_hash: str,
) -> str:
    agent = agent_instance if isinstance(agent_instance, dict) else {}
    config = getattr(resolved_llm, "config", None) or _session_agent_config_for_llm_slot(agent_instance, llm_slot)
    config_payload = _session_agent_runtime_config_fingerprint_payload(config)
    semantic_agent_fields = {
        key: agent.get(key)
        for key in (
            "agentId",
            "updatedAt",
            "status",
            "primaryMode",
            "promptTemplateId",
            "profileId",
            "roleKey",
            "llmBindings",
            "toolPolicy",
            "capabilities",
            "memoryPolicy",
            "workspacePolicy",
        )
        if key in agent
    }
    raw = json.dumps(
        {
            "workspacePath": str(Path(session_workspace).resolve()),
            "agent": semantic_agent_fields,
            "llmSlot": str(llm_slot or "").strip(),
            "llmModelId": str(getattr(resolved_llm, "model_id", "") or "").strip(),
            "mode": str(mode or "chat").strip(),
            "promptSnapshotHash": str(prompt_snapshot_hash or "").strip(),
            "config": config_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _session_agent_runtime_config_fingerprint_payload(config: Any) -> Any:
    """Keep session runtime reuse tied only to config consumed by chat Agents.

    The AppConfig also contains unrelated runtime domains (for example UI and
    pet state). Including the whole object causes a new Agent and transport on
    ordinary chat turns even when the dialogue model contract is unchanged.
    """

    if hasattr(config, "model_dump"):
        try:
            raw_payload: Any = config.model_dump(mode="json")
        except (TypeError, ValueError):
            raw_payload = config.model_dump()
    elif hasattr(config, "dict"):
        raw_payload = config.dict()
    elif isinstance(config, Mapping):
        raw_payload = dict(config)
    else:
        return repr(config)
    if not isinstance(raw_payload, Mapping):
        return raw_payload
    return {
        key: raw_payload[key]
        for key in _SESSION_AGENT_RUNTIME_CONFIG_FINGERPRINT_KEYS
        if key in raw_payload
    }


def _invalidate_session_agent_runtime_cache(session_id: str = "") -> int:
    normalized_session_id = str(session_id or "").strip()
    removed = 0
    with _SESSION_AGENT_RUNTIME_CACHE_LOCK:
        if not normalized_session_id:
            removed = len(_SESSION_AGENT_RUNTIME_CACHE)
            _SESSION_AGENT_RUNTIME_CACHE.clear()
            return removed
        prefix = f"{normalized_session_id}|"
        for cache_key in [key for key in _SESSION_AGENT_RUNTIME_CACHE if key.startswith(prefix)]:
            _SESSION_AGENT_RUNTIME_CACHE.pop(cache_key, None)
            removed += 1
    return removed


def _acquire_chat_agent_for_session(
    session_id: str,
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    resolved_llm: Any | None = None,
    mode: str = "chat",
    prompt_snapshot_hash: str = "",
) -> tuple[Any, dict[str, Any]]:
    normalized_session_id = str(session_id or "").strip()
    normalized_slot = str(llm_slot or SESSION_LLM_SLOT_DIALOGUE).strip() or SESSION_LLM_SLOT_DIALOGUE
    normalized_mode = str(mode or "chat").strip() or "chat"
    cache_allowed = bool(normalized_session_id and isinstance(agent_instance, dict) and normalized_mode == "chat")
    if not cache_allowed:
        with _SESSION_AGENT_RUNTIME_CACHE_LOCK:
            entry_count = len(_SESSION_AGENT_RUNTIME_CACHE)
        return (
            _create_chat_agent_for_session(
                session_workspace,
                agent_instance,
                llm_slot=normalized_slot,
                resolved_llm=resolved_llm,
                mode=normalized_mode,
            ),
            {"status": "bypassed", "hit": False, "entryCount": entry_count},
        )

    fingerprint = _session_agent_runtime_cache_fingerprint(
        session_workspace=session_workspace,
        agent_instance=agent_instance,
        llm_slot=normalized_slot,
        resolved_llm=resolved_llm,
        mode=normalized_mode,
        prompt_snapshot_hash=prompt_snapshot_hash,
    )
    cache_key = f"{normalized_session_id}|{normalized_slot}"
    with _SESSION_AGENT_RUNTIME_CACHE_LOCK:
        cached = _SESSION_AGENT_RUNTIME_CACHE.get(cache_key)
        if cached and str(cached.get("fingerprint") or "") == fingerprint:
            cached["lastAccess"] = _perf_counter()
            runtime_agent = cached.get("agent")
            entry_count = len(_SESSION_AGENT_RUNTIME_CACHE)
        else:
            runtime_agent = None
            entry_count = len(_SESSION_AGENT_RUNTIME_CACHE)
    if runtime_agent is not None:
        prepare_reuse = getattr(runtime_agent, "prepare_for_session_turn_reuse", None)
        if callable(prepare_reuse):
            prepare_reuse()
        return runtime_agent, {
            "status": "hit",
            "hit": True,
            "entryCount": entry_count,
        }

    runtime_agent = _create_chat_agent_for_session(
        session_workspace,
        agent_instance,
        llm_slot=normalized_slot,
        resolved_llm=resolved_llm,
        mode=normalized_mode,
    )
    with _SESSION_AGENT_RUNTIME_CACHE_LOCK:
        _SESSION_AGENT_RUNTIME_CACHE[cache_key] = {
            "agent": runtime_agent,
            "fingerprint": fingerprint,
            "lastAccess": _perf_counter(),
        }
        while len(_SESSION_AGENT_RUNTIME_CACHE) > _SESSION_AGENT_RUNTIME_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _SESSION_AGENT_RUNTIME_CACHE,
                key=lambda key: float(_SESSION_AGENT_RUNTIME_CACHE.get(key, {}).get("lastAccess") or 0.0),
            )
            _SESSION_AGENT_RUNTIME_CACHE.pop(oldest_key, None)
        entry_count = len(_SESSION_AGENT_RUNTIME_CACHE)
    return runtime_agent, {"status": "miss", "hit": False, "entryCount": entry_count}


def _create_chat_agent_for_session(
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    resolved_llm: Any | None = None,
    mode: str = "chat",
) -> Any:
    agent_config = getattr(resolved_llm, "config", None) or _session_agent_config_for_llm_slot(agent_instance, llm_slot)
    runtime_agent = call_agent_factory_with_supported_kwargs(
        create_chat_agent,
        mode=mode,
        workspace_path=session_workspace,
        config=agent_config,
    )
    try:
        runtime_agent._allow_session_subagent_auto_delegation = False
    except (AttributeError, TypeError):
        pass
    return runtime_agent


def create_chat_agent(workspace_path: str | Path | None = None, config: Any | None = None, mode: str = "chat") -> Any:
    return create_agent_runtime(
        mode=str(mode or "chat").strip() or "chat",
        workspace_path=str(workspace_path) if workspace_path else None,
        config=config,
    )


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


def _attach_session_llm_runtime_diagnostics(result: Any, diagnostics: dict[str, Any] | None) -> Any:
    if not isinstance(result, dict) or not isinstance(diagnostics, dict) or not diagnostics:
        return result
    allowed_keys = {
        "llmModelId",
        "runtimeProfileId",
        "providerId",
        "providerKind",
        "model",
    }
    sanitized = {
        str(key): str(value).strip()
        for key, value in diagnostics.items()
        if str(key or "").strip() in allowed_keys and str(value or "").strip()
    }
    if not sanitized:
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    for key, value in sanitized.items():
        metadata.setdefault(key, value)
    result["metadata"] = metadata
    llm_failure = dict(result.get("llm_failure") or {}) if isinstance(result.get("llm_failure"), dict) else {}

    def fill_empty(key: str, value: str) -> None:
        if value and not str(llm_failure.get(key) or "").strip():
            llm_failure[key] = value

    fill_empty("provider", sanitized.get("providerId") or sanitized.get("provider") or "")
    fill_empty("provider_id", sanitized.get("providerId") or "")
    fill_empty("providerId", sanitized.get("providerId") or "")
    fill_empty("provider_kind", sanitized.get("providerKind") or "")
    fill_empty("providerKind", sanitized.get("providerKind") or "")
    fill_empty("model", sanitized.get("model") or "")
    fill_empty("llm_model_id", sanitized.get("llmModelId") or "")
    fill_empty("llmModelId", sanitized.get("llmModelId") or "")
    fill_empty("runtime_profile_id", sanitized.get("runtimeProfileId") or "")
    fill_empty("runtimeProfileId", sanitized.get("runtimeProfileId") or "")
    result["llm_failure"] = llm_failure
    return result



def _build_llm_image_attachments(session_id: str, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for attachment in _normalize_message_attachments(attachments):
        artifact_id = str(attachment.get("artifactId") or "").strip()
        if not artifact_id:
            continue
        try:
            prepared.append(resolve_session_image_attachment_data_url(session_id, artifact_id))
        except (FileNotFoundError, OSError, SessionValidationError) as exc:
            _record_session_attachment_event(
                session_id,
                "prepare_failed",
                attachment,
                outcome=type(exc).__name__,
            )
            raise SessionValidationError(f"Image attachment could not be prepared: {artifact_id}") from exc
    return prepared



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


def _make_local_runtime_turn_error(
    raw_error: Any,
    *,
    lang: str,
    error_type: str,
    reason_code: str,
    reason_summary: str,
    reason_detail: str = "",
    turn_id: str = "",
    model: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_reason_summary = trim_lines(reason_summary, max_lines=2)
    normalized_reason_detail = trim_lines(reason_detail or raw_error, max_lines=4)
    message = text_for(
        lang,
        zh="运行提示：本轮没有进入模型调用，因为本地 Agent 模型槽位无法解析。",
        en="Runtime notice: this turn did not reach the model call because the local Agent model slot could not be resolved.",
    )
    if normalized_reason_summary:
        message = f"{message} 原因：{normalized_reason_summary}。" if lang == "zh" else f"{message} Reason: {normalized_reason_summary}."
    payload: dict[str, Any] = {
        "message": message,
        "error_type": str(error_type or "runtime_error").strip() or "runtime_error",
        "reason_code": str(reason_code or "").strip(),
        "reason_summary": normalized_reason_summary,
        "reason_detail": normalized_reason_detail,
        "http_status": 0,
        "provider": "",
        "provider_host": "",
        "provider_error_type": "",
        "provider_error_message": "",
        "model": str(model or "").strip(),
        "recoverable": False,
        "timestamp": _now_timestamp(),
        "turn_id": str(turn_id or "").strip(),
    }
    if extra:
        payload["extra"] = {str(key): value for key, value in extra.items() if str(key or "").strip()}
    return payload



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


def _session_agent_unavailable_message(reason: str, *, lang: str) -> str:
    if str(reason or "").strip() == "archived_agent":
        return text_for(
            lang,
            zh="当前会话引用的 Agent 已归档，不能继续运行。请在 Agent 管理中心选择 active Agent 或显式恢复后再发送。",
            en="This session references an archived Agent and cannot run. Choose an active Agent in Agent Center or explicitly restore it first.",
        )
    return text_for(
        lang,
        zh="当前会话缺少有效 Agent，不能继续运行。请在 Agent 管理中心选择 active Agent 后再发送。",
        en="This session has no valid Agent and cannot run. Choose an active Agent in Agent Center first.",
    )


def _record_session_agent_unavailable_event(
    session_id: str,
    *,
    agent_id: str,
    reason: str,
    agent_status: str = "",
) -> None:
    normalized_reason = str(reason or "").strip() or "missing_agent"
    event_code = (
        "conversation.turn.blocked_archived_agent"
        if normalized_reason == "archived_agent"
        else "conversation.turn.blocked_missing_agent"
    )
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_blocked",
            event_code,
            message="Web chat turn blocked because the session Agent is unavailable.",
            level="warning",
            outcome="blocked",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "reason": normalized_reason,
                "agentStatus": str(agent_status or "").strip(),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene unavailable agent log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_attachment_event(
    session_id: str,
    phase: str,
    attachment: dict[str, Any],
    *,
    outcome: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            f"attachment_{phase}",
            f"conversation.attachment.{phase}",
            level="info",
            outcome=outcome,
            message=f"Conversation image attachment {phase}.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "attachment": _safe_attachment_log_summary([attachment])[0] if attachment else {},
            },
            lifecycle=True,
        )
    except Exception:
        return


def _safe_attachment_log_summary(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for item in _normalize_message_attachments(attachments):
        summary.append(
            {
                "artifactId": str(item.get("artifactId") or "").strip(),
                "filename": str(item.get("filename") or "").strip(),
                "contentType": str(item.get("contentType") or "").strip(),
                "sizeBytes": _coerce_nonnegative_int(item.get("sizeBytes") or 0),
                "kind": str(item.get("kind") or "").strip(),
            }
        )
    return summary


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


def _record_session_llm_usage_event(
    session_id: str,
    turn_id: str,
    llm_usage: dict[str, Any] | None,
) -> None:
    normalized = _normalize_turn_llm_usage(llm_usage)
    source = str((normalized or {}).get("source") or "missing").strip() or "missing"
    observed = source == "provider_usage"
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "source": source,
        "inputTokens": int((normalized or {}).get("inputTokens") or 0),
        "outputTokens": int((normalized or {}).get("outputTokens") or 0),
        "totalTokens": int((normalized or {}).get("totalTokens") or 0),
        "cachedInputTokens": int((normalized or {}).get("cachedInputTokens") or 0),
        "cacheReadInputTokens": int((normalized or {}).get("cacheReadInputTokens") or (normalized or {}).get("cachedInputTokens") or 0),
        "cacheCreationInputTokens": int((normalized or {}).get("cacheCreationInputTokens") or 0),
        "uncachedInputTokens": int((normalized or {}).get("uncachedInputTokens") or 0),
        "cacheHitRate": float((normalized or {}).get("cacheHitRate") or 0.0),
        "promptCacheScope": str((normalized or {}).get("promptCacheScope") or "").strip(),
        "promptCachePartition": str((normalized or {}).get("promptCachePartition") or "").strip(),
        "llmModelId": str((normalized or {}).get("llmModelId") or "").strip(),
        "provider": str((normalized or {}).get("provider") or "").strip(),
        "model": str((normalized or {}).get("model") or "").strip(),
    }
    event_code = "conversation.llm_usage.recorded" if observed else "conversation.llm_usage.missing"
    try:
        result = record_runtime_scene_event(
            "conversation",
            "llm_usage",
            event_code,
            level="info" if observed else "warning",
            outcome="recorded" if observed else "missing",
            message="Conversation turn LLM usage recorded." if observed else "Conversation turn LLM usage missing.",
            fields=fields,
            child_log_path=f"conversations/{_safe_session_workspace_token(str(session_id or '').strip())}-turns.jsonl",
            child_log_payload=fields,
            lifecycle=False,
        )
        if isinstance(result, dict) and result.get("accepted") is False:
            reason = str(result.get("reason") or "unknown").strip() or "unknown"
            _debug_logger.warning(
                (
                    "conversation llm usage runtime scene event rejected: "
                    f"eventCode={event_code} reason={reason} "
                    f"sessionId={fields['sessionId']} turnId={fields['turnId']} "
                    f"source={source} inputTokens={fields['inputTokens']} "
                    f"cachedInputTokens={fields['cachedInputTokens']}"
                ),
                tag="CHAT",
            )
    except Exception:
        return


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


def _record_session_agent_binding_recovered_event(session_id: str, *, agent_id: str) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_binding",
            "conversation.agent_binding.recovered",
            message="Recovered a direct-session Agent binding from stale missing-agent metadata.",
            level="info",
            outcome="recovered",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": "session_agent_metadata_repair",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_child_direct_binding_repaired_event(
    session_id: str,
    *,
    agent_id: str,
    previous_direct_session_id: str,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    previous_session_id = str(previous_direct_session_id or "").strip()
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_child_direct_binding_repaired",
            "session.agent_child_direct_binding_repaired",
            level="warning",
            outcome="repaired",
            message="Root session repaired an Agent directSessionId that pointed at one of its child sessions.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "previousDirectSessionId": previous_session_id,
                "source": "session_child_contract_repair",
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "previous_direct_session_id": previous_session_id,
                "source": "session_child_contract_repair",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_binding_updated_event(
    session_id: str,
    *,
    agent_id: str,
    source: str,
    prompt_template_id: str = "",
    role_key: str = "",
) -> None:
    normalized_session_id = str(session_id or "").strip()
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_binding_updated",
            "session.agent_binding_updated",
            level="info",
            outcome="updated",
            message="Session Agent binding updated.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "prompt_template_id": str(prompt_template_id or "").strip(),
                "role_key": str(role_key or "").strip(),
                "source": str(source or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_missing_index_event(
    summary: dict[str, Any],
    *,
    source: str,
) -> None:
    session_id = str(summary.get("id") or "").strip()
    if not session_id:
        return
    agent_status_code = str(summary.get("agentStatusCode") or "").strip()
    agent_id = str(summary.get("agentId") or summary.get("agentMissingId") or "").strip()
    normalized_source = str(source or "").strip()
    dedupe_key = (str(PROJECT_ROOT.resolve()), session_id, agent_id, agent_status_code, normalized_source)
    with _SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in _SESSION_MISSING_INDEX_EVENT_KEYS:
            return
        _SESSION_MISSING_INDEX_EVENT_KEYS.add(dedupe_key)
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_missing",
            "session.agent_missing.hidden_from_index",
            level="info",
            outcome="hidden_control",
            message="Known stale session hidden from indexes because its bound Agent is missing or archived.",
            fields={
                "sessionId": session_id,
                "agentId": agent_id,
                "agentStatusCode": agent_status_code,
                "source": normalized_source,
                "hiddenFromIndex": True,
                "controlSignal": True,
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": session_id,
                "agent_id": agent_id,
                "agent_status_code": agent_status_code,
                "agent_status_message": trim_lines(str(summary.get("agentStatusMessage") or ""), max_lines=2),
                "source": normalized_source,
                "hidden_from_index": True,
                "control_signal": True,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_missing_index_batch_event(
    summaries: list[dict[str, Any]],
    *,
    source: str,
) -> None:
    normalized_source = str(source or "").strip()
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    hidden_count = 0
    for summary in list(summaries or []):
        if not isinstance(summary, dict):
            continue
        session_id = str(summary.get("id") or "").strip()
        if not session_id:
            continue
        agent_id = str(summary.get("agentId") or summary.get("agentMissingId") or "").strip()
        agent_status_code = str(summary.get("agentStatusCode") or "").strip()
        dedupe_key = (session_id, agent_id, agent_status_code)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        hidden_count += 1
        if len(samples) < 8:
            samples.append(
                {
                    "sessionId": session_id,
                    "agentId": agent_id,
                    "agentStatusCode": agent_status_code,
                    "agentStatusMessage": trim_lines(str(summary.get("agentStatusMessage") or ""), max_lines=2),
                }
            )
    if hidden_count <= 0:
        return
    dedupe_key = (
        str(PROJECT_ROOT.resolve()),
        normalized_source,
        hidden_count,
        tuple((item["sessionId"], item["agentId"], item["agentStatusCode"]) for item in samples),
    )
    with _SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in _SESSION_MISSING_INDEX_BATCH_EVENT_KEYS:
            return
        _SESSION_MISSING_INDEX_BATCH_EVENT_KEYS.add(dedupe_key)
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_missing_batch",
            "session.agent_missing.hidden_from_index.batch",
            level="info",
            outcome="hidden_control",
            message="Known stale sessions hidden from indexes because their bound Agents are missing or archived.",
            fields={
                "source": normalized_source,
                "hiddenCount": hidden_count,
                "sampleSessions": samples,
                "sampleCount": len(samples),
                "hiddenFromIndex": True,
                "controlSignal": True,
            },
            lifecycle=False,
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


def _record_agent_directory_conversation_index_event(
    agent: dict[str, Any],
    *,
    session_id: str,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    agent_id = str(agent.get("agentId") or "").strip()
    if not normalized_session_id or not agent_id:
        return
    dedupe_key = (str(PROJECT_ROOT.resolve()), normalized_session_id, agent_id)
    with _SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in _AGENT_DIRECTORY_INDEX_EVENT_KEYS:
            return
        _AGENT_DIRECTORY_INDEX_EVENT_KEYS.add(dedupe_key)
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_directory_index",
            "session.agent_directory_index_added",
            level="info",
            outcome="indexed",
            message="Agent Directory direct session added to the conversation index.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_direct_session_collision_repaired_event(
    *,
    preserved_session_ids: list[str],
    repaired: list[dict[str, str]],
) -> None:
    cleaned = [
        {
            "agentId": str(item.get("agentId") or "").strip(),
            "agentCode": str(item.get("agentCode") or "").strip(),
            "previousSessionId": str(item.get("previousSessionId") or "").strip(),
            "replacementSessionId": str(item.get("replacementSessionId") or "").strip(),
        }
        for item in list(repaired or [])
        if str(item.get("agentId") or "").strip()
    ]
    if not cleaned:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_direct_session_collision",
            "session.agent_direct_session_collision.repaired",
            level="warning",
            outcome="repaired",
            message="Duplicate active Agent directSessionId bindings were repaired before building the session index.",
            fields={
                "preservedSessionId": str((preserved_session_ids or [""])[0] or "").strip(),
                "preservedSessionIds": [str(item or "").strip() for item in list(preserved_session_ids or []) if str(item or "").strip()],
                "repairedCount": len(cleaned),
                "repairedAgents": cleaned[:12],
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_directory_conversation_materialized_event(
    agent: dict[str, Any],
    *,
    session_id: str,
    source: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_directory_materialize",
            "session.agent_directory_conversation_materialized",
            level="info",
            outcome="materialized",
            message="Agent Directory direct session materialized into chat state.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "agent_id": str(agent.get("agentId") or "").strip(),
                "agent_code": str(agent.get("agentCode") or "").strip(),
                "source": str(source or "").strip(),
                "action": "materialized_from_agent_directory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_legacy_model_fields_repaired_event(
    session_id: str,
    *,
    agent_id: str,
    previous_fields: dict[str, str],
    prompt_template_id: str = "",
    role_key: str = "",
) -> None:
    normalized_session_id = str(session_id or "").strip()
    cleaned_previous = {
        key: trim_lines(str(value or ""), max_lines=1)
        for key, value in dict(previous_fields or {}).items()
        if str(value or "").strip()
    }
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_legacy_model_fields_repaired",
            "session.agent_legacy_model_fields_repaired",
            level="info",
            outcome="repaired",
            message="Session legacy Agent model fields were removed from chat state.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "removedFieldNames": sorted(cleaned_previous),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": "AgentInstance",
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "removed_field_names": sorted(cleaned_previous),
                "previous_fields": cleaned_previous,
                "prompt_template_id": str(prompt_template_id or "").strip(),
                "role_key": str(role_key or "").strip(),
                "source": "AgentInstance",
                "action": "legacy_model_fields_removed",
            },
            lifecycle=True,
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


def _record_session_turn_tool_calls(
    session_id: str,
    turn_id: str,
    tool_calls: list[dict[str, Any]],
) -> None:
    for index, tool_call in enumerate(tool_calls or []):
        if not isinstance(tool_call, dict):
            continue
        _record_session_turn_subpackage_event(
            session_id,
            turn_id,
            "tool_calls.jsonl",
            {
                "index": index,
                "toolCallId": str(
                    tool_call.get("id")
                    or tool_call.get("toolCallId")
                    or tool_call.get("tool_call_id")
                    or ""
                ).strip(),
                "name": str(tool_call.get("name") or "").strip(),
                "status": str(tool_call.get("status") or "").strip(),
                "summary": trim_lines(tool_call.get("summary") or "", max_lines=3),
                "owner": str(tool_call.get("owner") or tool_call.get("agent") or "main").strip(),
                "trace_path": str(tool_call.get("tracePath") or tool_call.get("trace_path") or "").strip(),
            },
            phase="turn_tool_call",
            event_code="conversation.turn.tool_call",
            outcome=str(tool_call.get("status") or "observed").strip() or "observed",
            message=f"Conversation turn tool call: {tool_call.get('name') or 'tool'}.",
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


def _record_session_turn_error(
    session_id: str,
    turn_error: dict[str, Any],
    *,
    raw_error: str = "",
    status: str = "failed",
    active_task: dict[str, Any] | None = None,
) -> None:
    timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
    error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    message = {
        "role": "system",
        "content": str(turn_error.get("message") or "").strip(),
        "timestamp": timestamp,
        "error_type": error_type,
        "turn_id": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
    }
    _append_session_workspace_log(
        session_id,
        message,
        event="turn_error",
        status=status,
        active_task=active_task,
    )
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_error",
            "conversation.turn_error",
            level="error",
            outcome=status,
            message=str(turn_error.get("message") or "Conversation turn failed."),
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
                "errorType": error_type,
                "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
                "reasonSummary": str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip(),
                "reasonDetail": str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip(),
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
                "recoverable": bool(turn_error.get("recoverable", True)),
                "rawErrorPreview": trim_lines(raw_error, max_lines=2),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-errors.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_error.get("turn_id") or turn_error.get("turnId") or "").strip(),
                "status": status,
                "error_type": error_type,
                "message": str(turn_error.get("message") or "").strip(),
                "reason_code": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
                "reason_summary": str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip(),
                "reason_detail": str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip(),
                "http_status": _coerce_nonnegative_int(turn_error.get("http_status") or turn_error.get("httpStatus")) or 0,
                "provider": str(turn_error.get("provider") or "").strip(),
                "provider_host": str(turn_error.get("provider_host") or turn_error.get("providerHost") or "").strip(),
                "provider_error_type": str(turn_error.get("provider_error_type") or turn_error.get("providerErrorType") or "").strip(),
                "provider_error_message": str(turn_error.get("provider_error_message") or turn_error.get("providerErrorMessage") or "").strip(),
                "model": str(turn_error.get("model") or "").strip(),
                "chain_stage": str(turn_error.get("chain_stage") or turn_error.get("chainStage") or "").strip(),
                "event_code": str(turn_error.get("event_code") or turn_error.get("eventCode") or "").strip(),
                "trace_id": str(turn_error.get("trace_id") or turn_error.get("traceId") or "").strip(),
                "protocol": str(turn_error.get("protocol") or "").strip(),
                "recoverable": bool(turn_error.get("recoverable", True)),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene turn error log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_turn_circuit_breaker_event(
    session_id: str,
    result: Any,
    *,
    turn_id: str = "",
    turn_index: int,
) -> None:
    if not isinstance(result, dict):
        return
    llm_failure = result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else {}
    raw_error = _provider_failure_raw_error(result)
    error_type = _failure_error_type(raw_error)
    try:
        record_runtime_scene_event(
            "conversation",
            "turn_circuit_breaker",
            "conversation.turn_circuit_breaker",
            level="error",
            outcome="failed",
            message="Chat turn stopped after provider failure budget was exhausted.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "errorType": error_type,
                "llmFailureCategory": str(llm_failure.get("category") or "").strip(),
                "retryable": bool(llm_failure.get("retryable", True)),
                "attempts": _coerce_nonnegative_int(llm_failure.get("attempts") or 0),
                "maxAttempts": _coerce_nonnegative_int(llm_failure.get("max_attempts") or 0),
                "consecutiveFailures": _coerce_nonnegative_int(llm_failure.get("consecutive_failures") or 0),
                "continuationTurn": max(0, int(turn_index or 0)),
                "stopReason": trim_lines(llm_failure.get("stop_reason") or "", max_lines=2),
                "rawErrorPreview": trim_lines(raw_error, max_lines=2),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-circuit-breaker.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "error_type": error_type,
                "llm_failure": dict(llm_failure),
                "continuation_turn": max(0, int(turn_index or 0)),
                "raw_error": trim_lines(raw_error, max_lines=6),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene circuit breaker log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    _record_provider_failure_signal(
        session_id=session_id,
        turn_id=str(turn_id or "").strip(),
        error_type=error_type,
        raw_error=raw_error,
        related_event_code="conversation.turn_circuit_breaker",
        metadata={
            "continuationTurn": max(0, int(turn_index or 0)),
        },
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


def _append_session_workspace_log(
    session_id: str,
    message: dict[str, Any],
    *,
    event: str,
    status: str,
    active_task: dict[str, Any] | None = None,
) -> None:
    try:
        workspace = _ensure_session_workspace(session_id)
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        role = str(message.get("role") or "").strip().lower() or "message"
        record = {
            "timestamp": str(message.get("timestamp") or _now_timestamp()).strip(),
            "session_id": str(session_id or "").strip(),
            "event": str(event or "message").strip() or "message",
            "status": str(status or "").strip(),
            "role": role,
            "content": _sanitize_message_content(role, message.get("content") or ""),
            "thought": _sanitize_thought_text(message.get("thought") or ""),
            "mental_snapshot": _normalize_mental_snapshot(message.get("mental_snapshot") or message.get("mentalSnapshot")),
            "attachments": _safe_attachment_log_summary(
                message.get("attachments") or message.get("imageAttachments") or []
            ),
            "tool_calls": _normalize_persisted_tool_calls(
                message.get("tool_calls") or message.get("toolCalls") or []
            ),
            "feedback_events": _normalize_persisted_feedback_events(
                message.get("feedback_events") or message.get("feedbackEvents") or []
            ),
            "active_task": active_task if isinstance(active_task, dict) else {},
        }
        with (logs_dir / "conversation.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        content = str(record["content"] or "").strip()
        thought = str(record["thought"] or "").strip()
        tool_names = ", ".join(
            str(item.get("name") or "").strip()
            for item in list(record["tool_calls"] or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        )
        md_lines = [
            f"## {record['timestamp']} {role}",
            "",
            f"- event: {record['event']}",
            f"- status: {record['status'] or 'observed'}",
        ]
        if tool_names:
            md_lines.append(f"- tools: {tool_names}")
        if record["feedback_events"]:
            md_lines.append(f"- feedback events: {len(record['feedback_events'])}")
        md_lines.extend(["", content or "(empty)", ""])
        if thought:
            md_lines.extend(["```thought", thought, "```", ""])
        with (logs_dir / "conversation.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(md_lines) + "\n")
    except Exception as exc:
        _debug_logger.warning(
            f"session workspace log skipped: {type(exc).__name__}: {exc}",
            tag="CHAT",
        )


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_tool_call_status(value: Any, *, default: str = "done") -> str:
    status = str(value or "").strip().lower()
    if status in {
        "running",
        "pending",
        "queued",
        "thinking",
        "tooling",
        "answering",
        "done",
        "success",
        "succeeded",
        "completed",
        "finished",
        "ready",
        "degraded",
        "recovered",
        "observed",
        "failed",
        "error",
        "blocked",
        "cancelled",
        "no_result",
        "submitted",
        "in_progress",
        "timeout",
        "timed_out",
    }:
        if status in {"success", "succeeded", "completed", "finished", "ready", "observed"}:
            return "done"
        if status == "error":
            return "failed"
        if status in {"timeout", "timed_out"}:
            return "timeout"
        return status
    return default


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


def _looks_like_tool_call_failure_summary(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.search(
            r"(?i)(^\s*\[(?:超时|timeout|failed|error)\]|执行超时|timed\s+out|timeout(?:\s+expired)?|tool\s+failed|工具执行失败|调用失败|traceback|exception\b)",
            text,
        )
    )


def _tool_call_name(raw: Any) -> str:
    if isinstance(raw, dict):
        function_block = raw.get("function") or {}
        if not isinstance(function_block, dict):
            function_block = {}
        return str(
            raw.get("name")
            or raw.get("tool_name")
            or function_block.get("name")
            or ""
        ).strip()
    return str(raw or "").strip()


def _normalize_persisted_tool_calls(value: Any) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in list(value or []):
        name = _tool_call_name(item)
        if not name:
            continue
        status = _normalize_tool_call_status(
            item.get("status") if isinstance(item, dict) else "",
            default="done",
        )
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if isinstance(item, dict):
            call_id = str(
                item.get("callId")
                or item.get("toolCallId")
                or item.get("tool_call_id")
                or item.get("id")
                or ""
            ).strip()
            if call_id:
                entry["callId"] = call_id
            summary = trim_lines(
                item.get("summary")
                or item.get("result_preview")
                or item.get("resultPreview")
                or item.get("error")
                or "",
                max_lines=2,
            )
            if summary:
                entry["summary"] = summary
            failure_hint = summary or item.get("error") or ""
            if _looks_like_tool_call_failure_summary(failure_hint):
                entry["status"] = "timeout" if re.search(r"(?i)(超时|timed\s+out|timeout)", str(failure_hint or "")) else "failed"
            arguments = _safe_tool_argument_details(
                item.get("arguments") if isinstance(item.get("arguments"), dict) else item.get("args")
            )
            if arguments:
                entry["arguments"] = arguments
            result_preview = _trim_tool_detail_text(
                item.get("resultPreview") or item.get("result_preview") or item.get("result"),
                max_chars=1200,
                max_lines=10,
            )
            if result_preview:
                entry["resultPreview"] = result_preview
            terminal_facts = _sandbox_terminal_result_facts(
                item.get("result") or item.get("resultPreview") or item.get("result_preview")
            ) or _sandbox_terminal_result_facts(item)
            if terminal_facts:
                entry.update(terminal_facts)
                if terminal_facts.get("formattedOutput"):
                    entry["resultPreview"] = str(terminal_facts["formattedOutput"])
            result_type = str(item.get("resultType") or item.get("result_type") or "").strip()
            if result_type:
                entry["resultType"] = result_type
            result_length = _coerce_tool_number(item.get("resultLength") or item.get("result_length"))
            if result_length is not None:
                entry["resultLength"] = result_length
            error = _trim_tool_detail_text(item.get("error"), max_chars=1200, max_lines=10)
            if error:
                entry["error"] = error
            duration_ms = _coerce_tool_number(item.get("durationMs") or item.get("duration_ms"))
            if duration_ms is not None:
                entry["durationMs"] = duration_ms
            duration_seconds = _coerce_tool_number(item.get("durationSeconds") or item.get("duration_seconds") or item.get("elapsedSeconds"))
            if duration_seconds is not None:
                entry["durationSeconds"] = duration_seconds
            timeout_seconds = _coerce_tool_number(item.get("timeoutSeconds") or item.get("timeout_seconds"))
            if timeout_seconds is not None:
                entry["timeoutSeconds"] = timeout_seconds
            trace_path = str(item.get("tracePath") or item.get("trace_path") or "").strip()
            if trace_path:
                entry["tracePath"] = trace_path
            _copy_tool_result_fact_fields(item, entry)
            if entry.get("semanticStatus"):
                entry["status"] = _normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
        tool_calls.append(entry)
    return tool_calls


def _normalize_message_tool_calls(value: Any) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in _normalize_persisted_tool_calls(value):
        entry = {
            "name": str(item.get("name") or "").strip(),
            "status": _normalize_tool_call_status(item.get("status"), default="done"),
        }
        summary = trim_lines(item.get("summary") or "", max_lines=2)
        if summary:
            entry["summary"] = summary
        for key in (
            "callId",
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "transportStatus",
            "semanticStatus",
            "failureClass",
            "exitCode",
            "timedOut",
            "resultKind",
            "truncated",
            "originalLength",
            "tracePath",
            "terminalSessionId",
            "terminalStatus",
            "sessionOpen",
            "formattedOutput",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["name"]:
            tool_calls.append(entry)
    return tool_calls


def _normalize_feedback_event_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind in {"thought", "mental", "tool", "status", "assistant_text"}:
        return kind
    return ""


def _normalize_persisted_feedback_events(value: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        if not isinstance(item, dict):
            continue
        kind = _normalize_feedback_event_kind(item.get("kind"))
        if not kind:
            continue
        sequence = _coerce_nonnegative_int(item.get("sequence"))
        if sequence <= 0:
            sequence = index
        status = _normalize_tool_call_status(item.get("status"), default="done")
        entry: dict[str, Any] = {
            "sequence": sequence,
            "kind": kind,
            "status": status,
        }
        timestamp = str(item.get("timestamp") or item.get("createdAt") or item.get("created_at") or "").strip()
        if timestamp:
            entry["timestamp"] = timestamp
        name = str(item.get("name") or item.get("label") or "").strip()
        if name:
            entry["name"] = name
        call_id = str(item.get("callId") or item.get("toolCallId") or item.get("tool_call_id") or "").strip()
        if call_id:
            entry["callId"] = call_id
        summary = trim_lines(
            item.get("summary")
            or item.get("resultPreview")
            or item.get("result_preview")
            or item.get("error")
            or "",
            max_lines=2,
        )
        if summary:
            entry["summary"] = summary
        if kind == "assistant_text":
            content = _sanitize_message_content("assistant", item.get("text") or item.get("content") or summary)
            if content:
                entry["content"] = content
        arguments = _safe_tool_argument_details(
            item.get("arguments") if isinstance(item.get("arguments"), dict) else item.get("args")
        )
        if arguments:
            entry["arguments"] = arguments
        result_preview = _trim_tool_detail_text(
            item.get("resultPreview") or item.get("result_preview") or item.get("result"),
            max_chars=1800 if kind == "thought" else 1200,
            max_lines=18 if kind == "thought" else 10,
        )
        if result_preview:
            entry["resultPreview"] = result_preview
        terminal_facts = _sandbox_terminal_result_facts(
            item.get("result") or item.get("resultPreview") or item.get("result_preview")
        ) or _sandbox_terminal_result_facts(item)
        if terminal_facts:
            entry.update(terminal_facts)
            if terminal_facts.get("formattedOutput"):
                entry["resultPreview"] = str(terminal_facts["formattedOutput"])
        result_type = str(item.get("resultType") or item.get("result_type") or "").strip()
        if result_type:
            entry["resultType"] = result_type
        result_length = _coerce_tool_number(item.get("resultLength") or item.get("result_length"))
        if result_length is not None:
            entry["resultLength"] = result_length
        error = _trim_tool_detail_text(item.get("error"), max_chars=1200, max_lines=10)
        if error:
            entry["error"] = error
        duration_ms = _coerce_tool_number(item.get("durationMs") or item.get("duration_ms"))
        if duration_ms is not None:
            entry["durationMs"] = duration_ms
        duration_seconds = _coerce_tool_number(item.get("durationSeconds") or item.get("duration_seconds") or item.get("elapsedSeconds"))
        if duration_seconds is not None:
            entry["durationSeconds"] = duration_seconds
        timeout_seconds = _coerce_tool_number(item.get("timeoutSeconds") or item.get("timeout_seconds"))
        if timeout_seconds is not None:
            entry["timeoutSeconds"] = timeout_seconds
        trace_path = str(item.get("tracePath") or item.get("trace_path") or "").strip()
        if trace_path:
            entry["tracePath"] = trace_path
        _copy_tool_result_fact_fields(item, entry)
        if entry.get("semanticStatus"):
            entry["status"] = _normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
        related_sequence = _coerce_nonnegative_int(item.get("relatedThoughtSequence") or item.get("related_thought_sequence"))
        if related_sequence > 0:
            entry["relatedThoughtSequence"] = related_sequence
        events.append(entry)
    events.sort(key=lambda event: _coerce_nonnegative_int(event.get("sequence")))
    return events[-120:]


def _normalize_message_feedback_events(value: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for item in _normalize_persisted_feedback_events(value):
        entry = {
            "sequence": _coerce_nonnegative_int(item.get("sequence")),
            "kind": str(item.get("kind") or "").strip(),
            "status": _normalize_tool_call_status(item.get("status"), default="done"),
        }
        for key in (
            "timestamp",
            "callId",
            "name",
            "summary",
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "transportStatus",
            "semanticStatus",
            "failureClass",
            "exitCode",
            "timedOut",
            "resultKind",
            "truncated",
            "originalLength",
            "tracePath",
            "relatedThoughtSequence",
            "terminalSessionId",
            "terminalStatus",
            "sessionOpen",
            "formattedOutput",
            "content",
            "text",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["sequence"] > 0 and entry["kind"]:
            events.append(entry)
    return events


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


def _assistant_timeline_events_by_turn(conversation_id: str) -> dict[str, list[dict[str, Any]]]:
    normalized_session_id = str(conversation_id or "").strip()
    if not normalized_session_id:
        return {}
    events_by_turn: dict[str, list[dict[str, Any]]] = {}
    tool_event_keys: dict[str, dict[str, int]] = {}
    journal_events = list(_load_session_conversation_events_cached(normalized_session_id))
    canonical_commentary_turn_ids: set[str] = set()
    for event in journal_events:
        if str(getattr(event, "event_type", "") or "").strip() != "assistant_item_committed":
            continue
        payload = dict(getattr(event, "payload", {}) or {})
        item_payload = dict(payload.get("item") or {})
        item_kind = str(payload.get("kind") or item_payload.get("kind") or "").strip().lower()
        item_text = _sanitize_message_content(
            "assistant",
            payload.get("text") or item_payload.get("text") or "",
        )
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if turn_id and item_kind == "commentary" and item_text:
            canonical_commentary_turn_ids.add(turn_id)
    for event in journal_events:
        turn_id = str(getattr(event, "turn_id", "") or "").strip()
        if not turn_id:
            continue
        event_type = str(getattr(event, "event_type", "") or "").strip()
        payload = dict(getattr(event, "payload", {}) or {})
        if event_type == "assistant_item_committed":
            item_payload = dict(payload.get("item") or {})
            item_kind = str(payload.get("kind") or item_payload.get("kind") or "").strip().lower()
            content = _sanitize_message_content(
                "assistant",
                payload.get("text") or item_payload.get("text") or "",
            )
            sequence = _coerce_nonnegative_int(getattr(event, "sequence", 0))
            if item_kind not in {"commentary", "reasoning"} or sequence <= 0 or not content:
                continue
            events_by_turn.setdefault(turn_id, []).append(
                {
                    "sequence": sequence,
                    "kind": "assistant_text" if item_kind == "commentary" else "thought",
                    "status": _normalize_tool_call_status(getattr(event, "status", ""), default="done"),
                    "content": content,
                    "source": "assistant_item_committed",
                }
            )
            continue
        if event_type == EVENT_ASSISTANT_DELTA_COMMITTED:
            if turn_id in canonical_commentary_turn_ids:
                continue
            sequence = _coerce_nonnegative_int(payload.get("feedbackSequence") or payload.get("feedback_sequence"))
            if sequence <= 0 and _is_assistant_timeline_segment_event(event):
                sequence = _coerce_nonnegative_int(getattr(event, "sequence", 0))
            content = _sanitize_message_content("assistant", payload.get("content") or "")
            if sequence <= 0 or not content:
                continue
            events_by_turn.setdefault(turn_id, []).append(
                {
                    "sequence": sequence,
                    "kind": "assistant_text",
                    "status": _normalize_tool_call_status(getattr(event, "status", ""), default="done"),
                    "content": content,
                }
            )
            continue
        if event_type not in {EVENT_TOOL_CALL_STARTED, EVENT_TOOL_RESULT, EVENT_CLI_TASK_SENT, EVENT_CLI_TASK_RESULT}:
            continue
        tool_event = _feedback_event_from_conversation_tool_event(event)
        if tool_event:
            if turn_id in canonical_commentary_turn_ids:
                tool_event["sequence"] = _coerce_nonnegative_int(getattr(event, "sequence", 0))
            items = events_by_turn.setdefault(turn_id, [])
            tool_key = _conversation_tool_timeline_key(event)
            previous_index = tool_event_keys.setdefault(turn_id, {}).get(tool_key) if tool_key else None
            if previous_index is not None and 0 <= previous_index < len(items):
                items[previous_index] = tool_event
            else:
                if tool_key:
                    tool_event_keys.setdefault(turn_id, {})[tool_key] = len(items)
                items.append(tool_event)
    return {
        turn_id: sorted(items, key=lambda item: _coerce_nonnegative_int(item.get("sequence")))
        for turn_id, items in events_by_turn.items()
        if any(str(item.get("kind") or "") in {"assistant_text", "thought"} for item in items)
    }


def _is_assistant_timeline_segment_event(event: Any) -> bool:
    projection_kind = str(getattr(event, "projection_kind", "") or "").strip()
    source = str(getattr(event, "source", "") or "").strip()
    return projection_kind == "assistant_timeline_segment" or source == "session_ui_capture"


def _conversation_tool_timeline_key(event: Any) -> str:
    payload = dict(getattr(event, "payload", {}) or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    tool_id = str(
        getattr(event, "tool_call_id", "")
        or tool_call.get("id")
        or tool_call.get("toolCallId")
        or tool_call.get("tool_call_id")
        or tool_call.get("taskId")
        or ""
    ).strip()
    if tool_id:
        return f"id:{tool_id}"
    sequence = _coerce_nonnegative_int(tool_call.get("feedbackSequence") or tool_call.get("feedback_sequence"))
    if sequence > 0:
        return f"sequence:{sequence}"
    return ""


def _feedback_event_from_conversation_tool_event(event: Any) -> dict[str, Any]:
    payload = dict(getattr(event, "payload", {}) or {})
    tool_call = dict(payload.get("toolCall") or payload.get("tool_call") or payload)
    name = str(tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name") or "").strip()
    if not name:
        return {}
    sequence = _coerce_nonnegative_int(tool_call.get("feedbackSequence") or tool_call.get("feedback_sequence"))
    if sequence <= 0:
        sequence = _coerce_nonnegative_int(getattr(event, "sequence", 0))
    entry: dict[str, Any] = {
        "sequence": sequence,
        "kind": "tool",
        "status": _normalize_tool_call_status(tool_call.get("status") or getattr(event, "status", ""), default="running"),
        "name": name,
    }
    summary = trim_lines(
        tool_call.get("summary")
        or tool_call.get("resultPreview")
        or tool_call.get("result_preview")
        or tool_call.get("error")
        or "",
        max_lines=2,
    )
    if summary:
        entry["summary"] = summary
    arguments = _safe_tool_argument_details(
        tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else tool_call.get("args")
    )
    if arguments:
        entry["arguments"] = arguments
    result_preview = _trim_tool_detail_text(
        tool_call.get("resultPreview") or tool_call.get("result_preview") or tool_call.get("result"),
        max_chars=1200,
        max_lines=10,
    )
    if result_preview:
        entry["resultPreview"] = result_preview
    terminal_facts = _sandbox_terminal_result_facts(
        tool_call.get("result") or tool_call.get("resultPreview") or tool_call.get("result_preview")
    ) or _sandbox_terminal_result_facts(tool_call)
    if terminal_facts:
        entry.update(terminal_facts)
        if terminal_facts.get("formattedOutput"):
            entry["resultPreview"] = str(terminal_facts["formattedOutput"])
    error = _trim_tool_detail_text(tool_call.get("error"), max_chars=1200, max_lines=10)
    if error:
        entry["error"] = error
    for source_key, target_key in (
        ("durationMs", "durationMs"),
        ("duration_ms", "durationMs"),
        ("durationSeconds", "durationSeconds"),
        ("duration_seconds", "durationSeconds"),
        ("timeoutSeconds", "timeoutSeconds"),
        ("timeout_seconds", "timeoutSeconds"),
    ):
        if source_key in tool_call and target_key not in entry:
            value = _coerce_tool_number(tool_call.get(source_key))
            if value is not None:
                entry[target_key] = value
    _copy_tool_result_fact_fields(tool_call, entry)
    if entry.get("semanticStatus"):
        entry["status"] = _normalize_tool_call_status(entry.get("semanticStatus"), default=entry["status"])
    return entry


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


def _filter_redundant_assistant_timeline_events(
    events: list[dict[str, Any]],
    content: Any,
) -> list[dict[str, Any]]:
    content_key = _assistant_projection_text_key(content)
    if not content_key:
        return events
    filtered: list[dict[str, Any]] = []
    for event in events:
        if str(event.get("kind") or "").strip() == "assistant_text":
            text = _sanitize_message_content("assistant", event.get("text") or event.get("content") or "")
            text_key = _assistant_projection_text_key(text)
            if text_key and text_key in content_key:
                continue
        filtered.append(event)
    return filtered


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


def _normalize_session_turn_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    message = trim_lines(value.get("message") or value.get("summary") or "", max_lines=4)
    if not message:
        return None
    http_status = _coerce_nonnegative_int(value.get("httpStatus") or value.get("http_status"))
    return {
        "message": message,
        "errorType": str(value.get("errorType") or value.get("error_type") or "runtime_error").strip() or "runtime_error",
        "reasonCode": str(value.get("reasonCode") or value.get("reason_code") or "").strip(),
        "reasonSummary": str(value.get("reasonSummary") or value.get("reason_summary") or "").strip(),
        "reasonDetail": str(value.get("reasonDetail") or value.get("reason_detail") or "").strip(),
        "httpStatus": http_status if http_status > 0 else None,
        "provider": str(value.get("provider") or "").strip(),
        "providerHost": str(value.get("providerHost") or value.get("provider_host") or "").strip(),
        "providerErrorType": str(value.get("providerErrorType") or value.get("provider_error_type") or "").strip(),
        "providerErrorMessage": str(value.get("providerErrorMessage") or value.get("provider_error_message") or "").strip(),
        "model": str(value.get("model") or "").strip(),
        "chainStage": str(value.get("chainStage") or value.get("chain_stage") or "").strip(),
        "eventCode": str(value.get("eventCode") or value.get("event_code") or "").strip(),
        "traceId": str(value.get("traceId") or value.get("trace_id") or "").strip(),
        "protocol": str(value.get("protocol") or "").strip(),
        "recoverable": bool(value.get("recoverable", True)),
        "timestamp": str(value.get("timestamp") or value.get("createdAt") or value.get("created_at") or "").strip(),
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
    }


def _make_session_turn_error(
    raw_error: Any,
    *,
    lang: str,
    error_type: str = "",
    turn_id: str = "",
    llm_failure: dict[str, Any] | None = None,
    llm_payload_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_error_type = str(error_type or _failure_error_type(str(raw_error or ""))).strip() or "runtime_error"
    provider_reason = _provider_error_user_reason(raw_error, lang=lang)
    provider_diagnostics = _provider_error_diagnostics(raw_error, llm_failure=llm_failure)
    structured_failure = dict(llm_failure or {})
    payload_trace = dict(llm_payload_trace or {})

    def _failure_text(snake_key: str, camel_key: str, *, max_lines: int = 2) -> str:
        value = structured_failure.get(snake_key, structured_failure.get(camel_key, ""))
        return trim_lines(value, max_lines=max_lines)

    if normalized_error_type == "provider_upstream_error" and provider_reason.get("code") in {"", "provider_error"}:
        provider_reason = {
            **provider_reason,
            "code": "upstream_unavailable",
            "summary": text_for(
                lang,
                zh="provider 上游服务不可用或网关失败",
                en="provider upstream service is unavailable or failed at the gateway",
            ),
        }
    reason_code = _failure_text("reason_code", "reasonCode") or str(provider_reason.get("code") or "").strip()
    reason_summary = _failure_text("reason_summary", "reasonSummary") or str(
        provider_reason.get("summary") or ""
    ).strip()
    reason_detail = _failure_text("reason_detail", "reasonDetail", max_lines=4) or str(
        provider_reason.get("detail") or ""
    ).strip()
    chain_stage = _failure_text("chain_stage", "chainStage")
    event_code = _failure_text("event_code", "eventCode")
    trace_id = _failure_text("trace_id", "traceId") or str(payload_trace.get("traceId") or "").strip()
    protocol = _failure_text("protocol", "protocol") or str(
        payload_trace.get("selectedProtocol") or payload_trace.get("transport") or ""
    ).strip()
    structured_message = _failure_text("message", "message", max_lines=4)
    default_recoverable = normalized_error_type.startswith("provider_") or normalized_error_type in {
        "server_error",
        "network_error",
    }
    return {
        "message": structured_message
        or _user_visible_failure_summary(raw_error, lang=lang, provider_reason=provider_reason),
        "error_type": normalized_error_type,
        "reason_code": reason_code,
        "reason_summary": reason_summary,
        "reason_detail": reason_detail,
        "chain_stage": chain_stage,
        "event_code": event_code,
        "trace_id": trace_id,
        "protocol": protocol,
        "http_status": provider_diagnostics.get("http_status") or 0,
        "provider": provider_diagnostics.get("provider") or "",
        "provider_host": provider_diagnostics.get("provider_host") or "",
        "provider_error_type": provider_diagnostics.get("provider_error_type") or "",
        "provider_error_message": provider_diagnostics.get("provider_error_message") or "",
        "model": provider_diagnostics.get("model") or "",
        "recoverable": bool(structured_failure.get("retryable", default_recoverable)),
        "timestamp": _now_timestamp(),
        "turn_id": str(turn_id or "").strip(),
    }


def _session_turn_error_to_api(value: Any) -> dict[str, Any] | None:
    normalized = _normalize_session_turn_error(value)
    if normalized is None:
        return None
    if not normalized["timestamp"]:
        normalized["timestamp"] = _now_timestamp()
    return normalized


def _extract_chat_tool_calls(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    tool_calls = _normalize_persisted_tool_calls(result.get("tool_trace") or [])
    if tool_calls:
        return tool_calls
    return _normalize_persisted_tool_calls(result.get("tool_calls") or result.get("tools") or [])


def _extract_chat_feedback_events(result: Any, *, final_status: str = "") -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    events = _normalize_persisted_feedback_events(result.get("feedback_events") or result.get("feedbackEvents") or [])
    if not events:
        return []
    status_key = str(final_status or "").strip().lower()
    if not status_key or status_key in {"running", "queued"}:
        return events
    finalized: list[dict[str, Any]] = []
    latest_unfinished_index = -1
    failure_statuses = {"failed", "failed_runtime", "failed_provider", "timeout", "error"}
    should_fail_latest_unfinished = status_key in failure_statuses
    if should_fail_latest_unfinished:
        for index, item in enumerate(events):
            if str(item.get("status") or "").strip().lower() in {"running", "pending"}:
                latest_unfinished_index = index
    for index, item in enumerate(events):
        entry = dict(item)
        if str(entry.get("status") or "").strip().lower() in {"running", "pending"}:
            entry["status"] = (
                "done"
                if not should_fail_latest_unfinished or index < latest_unfinished_index
                else "failed"
            )
        finalized.append(entry)
    return finalized


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


def _make_turn_error_chat_message(
    turn_error: dict[str, Any],
    *,
    error_type: str,
    turn_id: str,
    provider_failure: bool,
) -> dict[str, Any]:
    timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
    reason_summary = str(turn_error.get("reason_summary") or turn_error.get("reasonSummary") or "").strip()
    reason_detail = str(turn_error.get("reason_detail") or turn_error.get("reasonDetail") or "").strip()
    visible_message = str(turn_error.get("message") or "").strip()
    if reason_summary and reason_summary not in visible_message:
        visible_message = f"{visible_message} 原因：{reason_summary}。".strip()
    message = _make_chat_message(
        "assistant",
        visible_message,
        metadata={
            "kind": "turn_error",
            "errorType": str(error_type or "").strip(),
            "turnId": str(turn_id or "").strip(),
            "recoverable": bool(turn_error.get("recoverable")),
            "providerFailure": bool(provider_failure),
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


def _looks_like_provider_error_text(text: Any) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(_PROVIDER_ERROR_PATTERN.search(value))


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


def _provider_error_user_reason(raw_error: Any, *, lang: str | None = None) -> dict[str, str]:
    language = lang or get_web_language()
    value = str(raw_error or "").strip()
    lower = value.lower()
    detail = _provider_error_reason_detail(value)

    def reason(code: str, zh: str, en: str) -> dict[str, str]:
        return {"code": code, "summary": text_for(language, zh=zh, en=en), "detail": detail}

    if "api key" in lower and ("额度" in value or "限额" in value or "用完" in value or "quota" in lower or "rate_limit" in lower):
        return reason("quota_exhausted", "API Key 额度或当日限额已用完", "API key quota or daily limit is exhausted")
    if (
        "prompt_cache_unsupported" in lower
        or "不支持显式 prompt cache" in value
        or "模型配置声明不支持 prompt cache" in value
    ):
        return reason(
            "prompt_cache_unsupported",
            "当前模型配置声明不支持 prompt cache",
            "the current model configuration declares prompt cache unsupported",
        )
    if "rate limit" in lower or "rate_limit" in lower or "429" in lower:
        return reason("rate_limited", "provider 正在限流", "provider is rate limiting requests")
    if "temperature" in lower and ("deprecated" in lower or "not supported" in lower or "unsupported" in lower):
        return reason("deprecated_sampling_parameter", "模型不接受当前采样参数，例如 temperature", "model rejected a sampling parameter such as temperature")
    if "top_p" in lower or "top_k" in lower:
        return reason("deprecated_sampling_parameter", "模型不接受当前采样参数，例如 top_p/top_k", "model rejected a sampling parameter such as top_p/top_k")
    if "context_length" in lower or "context length" in lower or "maximum context" in lower or "too many tokens" in lower:
        return reason("context_limit", "输入上下文超过模型限制", "input context exceeded the model limit")
    if "auth" in lower or "unauthorized" in lower or "forbidden" in lower or "401" in lower or "403" in lower:
        return reason("auth_failed", "provider 认证失败，请检查 API Key 或权限", "provider authentication failed; check the API key or permissions")
    if (
        "upstream_error" in lower
        or "upstream request failed" in lower
        or "badgateway" in lower
        or "bad gateway" in lower
        or "serviceunavailable" in lower
        or "service unavailable" in lower
    ):
        return reason("upstream_unavailable", "provider 上游服务不可用或网关失败", "provider upstream service is unavailable or failed at the gateway")
    if "timeout" in lower:
        return reason("timeout", "provider 响应超时", "provider response timed out")
    if _looks_like_provider_error_text(value):
        return reason("provider_error", "provider 返回了协议或服务错误", "provider returned a protocol or service error")
    return {"code": "", "summary": "", "detail": detail}


def _provider_error_reason_detail(raw_error: Any) -> str:
    value = str(raw_error or "").strip()
    if not value:
        return ""
    candidates: list[str] = []
    json_start = value.find("{")
    json_end = value.rfind("}")
    json_blobs = [value[json_start:json_end + 1]] if json_start >= 0 and json_end > json_start else []
    json_blobs.extend(re.findall(r"(?s)(\{.*?\})", value))
    for json_blob in json_blobs:
        try:
            parsed = json.loads(json_blob)
        except Exception:
            continue
        message = _extract_provider_error_message_from_json(parsed)
        if message:
            candidates.append(message)
    for pattern in (
        r"(?is)['\"]error['\"]\s*:\s*\{[^{}]*['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)['\"]message['\"]\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)\berror\s*:\s*\{[^{}]*\bmessage\s*:\s*['\"]([^'\"]+)['\"]",
        r"(?is)\bmessage\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"(?is)(?:invalid_request_error|rate_limit_error|authentication_error|permission_error|context_length_exceeded)\s*:\s*(.+)$",
        r"(?is)(?:AnthropicException|OpenAIException|BadGatewayError)\s*-\s*(.+)$",
    ):
        match = re.search(pattern, value)
        if match:
            candidates.append(match.group(1))
    for candidate in candidates:
        detail = _sanitize_provider_error_detail(candidate)
        if detail:
            return detail
    if len(value) <= 220 and not any(secret in value.lower() for secret in ("authorization", "bearer ", "sk-")):
        return _sanitize_provider_error_detail(value)
    return ""


def _provider_error_diagnostics(raw_error: Any, *, llm_failure: dict[str, Any] | None = None) -> dict[str, Any]:
    value = str(raw_error or "").strip()
    llm_failure = llm_failure if isinstance(llm_failure, dict) else {}
    diagnostics: dict[str, Any] = {
        "http_status": _coerce_nonnegative_int(
            llm_failure.get("http_status")
            or llm_failure.get("httpStatus")
            or llm_failure.get("status_code")
            or llm_failure.get("statusCode")
        ),
        "provider": str(llm_failure.get("provider") or "").strip(),
        "provider_host": _host_from_provider_url(llm_failure.get("api_base") or llm_failure.get("base_url") or llm_failure.get("baseUrl")),
        "provider_error_type": str(llm_failure.get("provider_error_type") or llm_failure.get("providerErrorType") or "").strip(),
        "provider_error_message": str(
            llm_failure.get("provider_error_message")
            or llm_failure.get("providerErrorMessage")
            or ""
        ).strip(),
        "model": str(llm_failure.get("model") or "").strip(),
    }
    for parsed in _iter_provider_error_json(value):
        if not diagnostics["provider_error_message"]:
            diagnostics["provider_error_message"] = _extract_provider_error_message_from_json(parsed)
        if not diagnostics["provider_error_type"]:
            diagnostics["provider_error_type"] = _extract_provider_error_type_from_json(parsed)
        if not diagnostics["http_status"]:
            diagnostics["http_status"] = _extract_provider_http_status_from_json(parsed)
    if not diagnostics["provider_error_message"]:
        diagnostics["provider_error_message"] = _provider_error_reason_detail(value)
    if not diagnostics["provider_error_type"]:
        type_match = re.search(
            r"(?i)\b(?:litellm\.)?([A-Za-z][A-Za-z0-9_]*(?:Error|Exception))\b",
            value,
        )
        diagnostics["provider_error_type"] = type_match.group(1) if type_match else ""
    if not diagnostics["http_status"]:
        diagnostics["http_status"] = _infer_provider_http_status(value)
    if not diagnostics["provider_host"]:
        host_match = re.search(r"(?i)\bbaseUrlHost['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)", value)
        diagnostics["provider_host"] = host_match.group(1) if host_match else ""
    diagnostics["provider_error_message"] = _sanitize_provider_error_detail(diagnostics["provider_error_message"])
    diagnostics["provider_error_type"] = _sanitize_provider_error_type(diagnostics["provider_error_type"])
    if diagnostics["http_status"] <= 0:
        diagnostics["http_status"] = 0
    return diagnostics


def _iter_provider_error_json(value: str) -> list[Any]:
    text = str(value or "").strip()
    if not text:
        return []
    blobs: list[str] = []
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start >= 0 and json_end > json_start:
        blobs.append(text[json_start:json_end + 1])
    blobs.extend(re.findall(r"(?s)(\{.*?\})", text))
    parsed_items: list[Any] = []
    seen: set[str] = set()
    for blob in blobs:
        candidate = blob.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed_items.append(json.loads(candidate))
            continue
        except Exception:
            pass
        try:
            parsed_items.append(json.loads(candidate.encode("utf-8").decode("unicode_escape")))
        except Exception:
            continue
    return parsed_items


def _extract_provider_error_type_from_json(value: Any) -> str:
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type") or error.get("code") or "").strip()
            if error_type:
                return error_type
        error_type = str(value.get("type") or value.get("code") or "").strip()
        if error_type and error_type != "error":
            return error_type
        for nested in value.values():
            error_type = _extract_provider_error_type_from_json(nested)
            if error_type:
                return error_type
    if isinstance(value, list):
        for item in value:
            error_type = _extract_provider_error_type_from_json(item)
            if error_type:
                return error_type
    return ""


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


def _sanitize_provider_error_type(value: Any) -> str:
    error_type = str(value or "").strip()
    if not error_type:
        return ""
    error_type = re.sub(r"[^A-Za-z0-9_.:-]", "", error_type)
    return error_type[:96]


def _extract_provider_error_message_from_json(value: Any) -> str:
    if isinstance(value, dict):
        error = value.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message
        message = str(value.get("message") or "").strip()
        if message:
            return message
        for nested in value.values():
            message = _extract_provider_error_message_from_json(nested)
            if message:
                return message
    if isinstance(value, list):
        for item in value:
            message = _extract_provider_error_message_from_json(item)
            if message:
                return message
    return ""


def _sanitize_provider_error_detail(value: Any) -> str:
    detail = trim_lines(value, max_lines=3)
    if not detail:
        return ""
    detail = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-***", detail)
    detail = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", detail)
    detail = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|authorization)(\s*[:=]\s*)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        detail,
    )
    if len(detail) > 320:
        detail = f"{detail[:317].rstrip()}..."
    return detail


def _user_visible_failure_summary(
    raw_error: Any,
    *,
    lang: str | None = None,
    exc: Exception | None = None,
    provider_reason: dict[str, str] | None = None,
) -> str:
    language = lang or get_web_language()
    text = str(raw_error or "").strip()
    if (
        "prompt_cache_unsupported" in text.lower()
        or "不支持显式 prompt cache" in text
        or "模型配置声明不支持 prompt cache" in text
    ):
        reason_summary = str((provider_reason or {}).get("summary") or "").strip()
        reason_line = text_for(
            language,
            zh=f"原因：{reason_summary}。" if reason_summary else "原因：当前模型配置声明不支持 prompt cache。",
            en=f"Reason: {reason_summary}." if reason_summary else "Reason: the current model configuration declares prompt cache unsupported.",
        )
        return text_for(
            language,
            zh=f"模型配置不满足本轮 prompt cache 要求，本轮已停止。{reason_line}请把当前模型的 prompt_cache.mode 配置为 automatic 或 explicit_cache_control，或关闭缓存强制要求。",
            en=f"The model configuration does not satisfy this turn's prompt-cache requirement, so the turn was stopped. {reason_line} Set this model's prompt_cache.mode to automatic or explicit_cache_control, or disable the cache requirement.",
        )
    if _looks_like_provider_error_text(text):
        reason_summary = str((provider_reason or {}).get("summary") or "").strip()
        reason_detail = str((provider_reason or {}).get("detail") or "").strip()
        visible_reason_detail = reason_detail if _provider_error_detail_safe_for_chat(reason_detail) else ""
        reason_line = text_for(
            language,
            zh=f"原因：{reason_summary}。" if reason_summary else "原因：provider 返回了错误。",
            en=f"Reason: {reason_summary}." if reason_summary else "Reason: the provider returned an error.",
        )
        detail_line = text_for(
            language,
            zh=f"具体报错：{visible_reason_detail}。" if visible_reason_detail else "",
            en=f"Provider detail: {visible_reason_detail}." if visible_reason_detail else "",
        )
        return text_for(
            language,
            zh=f"模型服务上游暂时失败，本轮没有完成。{reason_line}{detail_line}完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            en=f'The model provider failed upstream, so this turn did not complete. {reason_line}{detail_line} The full provider error was written to runtime logs; retry later or send "continue".',
        )
    reason = trim_lines(text, max_lines=2)
    summary = text_for(
        language,
        zh="网页工作台这一轮执行失败，请检查配置或稍后重试。",
        en="This web workbench turn failed. Check configuration and try again.",
    )
    if reason:
        return f"{summary}\n{reason}"
    if exc is not None:
        return f"{summary}\n{type(exc).__name__}"
    return summary


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


def _normalize_mental_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    raw_metrics = value.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
    history_tail: list[dict[str, Any]] = []
    if isinstance(value.get("historyTail"), list):
        history_source = value.get("historyTail")
    elif isinstance(value.get("history_tail"), list):
        history_source = value.get("history_tail")
    else:
        history_source = []
    for item in list(history_source or [])[-5:]:
        if isinstance(item, dict):
            history_tail.append({
                "cognitiveState": str(item.get("cognitiveState") or item.get("state") or item.get("cognitive_state") or "").strip(),
                "confidence": _coerce_confidence(item.get("confidence")),
                "timestamp": str(item.get("timestamp") or item.get("updatedAt") or item.get("updated_at") or "").strip(),
            })
    snapshot = {
        "mood": str(value.get("mood") or "").strip(),
        "feeling": str(value.get("feeling") or "").strip(),
        "whisper": str(value.get("whisper") or "").strip(),
        "summary": str(value.get("summary") or "").strip(),
        "cognitiveState": str(value.get("cognitiveState") or value.get("cognitive_state") or "").strip(),
        "confidence": _coerce_confidence(value.get("confidence")),
        "sampleSize": _coerce_nonnegative_int(value.get("sampleSize") or value.get("sample_size") or 0),
        "interventionCount": _coerce_nonnegative_int(
            value.get("interventionCount") or value.get("intervention_count") or 0
        ),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or "").strip(),
        "source": str(value.get("source") or "").strip(),
        "intervention": trim_lines(value.get("intervention") or "", max_lines=8),
        "metrics": metrics,
        "historyTail": history_tail,
    }
    if not snapshot["summary"]:
        snapshot["summary"] = snapshot["feeling"] or snapshot["whisper"]
    return snapshot


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


def _is_mental_model_enabled_for_turn(override: bool | None = None) -> bool:
    return resolve_feature_decision(
        "mental_model",
        config=get_config(),
        requested=override,
    ).effective_enabled


def _has_meaningful_mental_snapshot(snapshot: dict[str, Any] | None) -> bool:
    if not isinstance(snapshot, dict):
        return False
    return any(
        str(snapshot.get(key) or "").strip()
        for key in ("mood", "feeling", "whisper", "cognitiveState")
    )


def _live_mental_snapshot(state_info: dict[str, Any], lang: str) -> dict[str, Any] | None:
    mood = str((state_info or {}).get("mood") or "").strip()
    feeling = str((state_info or {}).get("feeling") or "").strip()
    whisper = str((state_info or {}).get("whisper") or "").strip()
    if not any((mood, feeling, whisper)):
        return None
    return {
        "mood": mood,
        "feeling": feeling,
        "whisper": whisper,
        "summary": feeling or whisper or text_for(
            lang,
            zh="当前心智层已给出最近一次状态。",
            en="The mental layer has produced a recent state.",
        ),
        "cognitiveState": "",
        "confidence": 0.0,
        "sampleSize": 0,
        "interventionCount": 0,
        "updatedAt": _now_timestamp(),
        "source": "state",
    }


def _build_turn_mental_snapshot(
    result: Any,
    lang: str,
    *,
    mental_model_enabled: bool | None = None,
    session_workspace: str | Path | None = None,
    session_id: str = "",
    turn_id: str = "",
) -> dict[str, Any] | None:
    if not _is_mental_model_enabled_for_turn(mental_model_enabled):
        return None
    state_snapshot = None
    explicit = None
    if isinstance(result, dict):
        explicit = _normalize_mental_snapshot(result.get("mental_snapshot") or result.get("mentalSnapshot"))
        if _has_meaningful_mental_snapshot(explicit):
            _record_mental_snapshot_selection(
                session_id=session_id,
                turn_id=turn_id,
                chosen_source="explicit",
                explicit=explicit,
                state_snapshot=None,
                runtime_snapshot=None,
                diagnosis_snapshot=None,
            )
            return explicit
        state_snapshot = _live_mental_snapshot(result.get("state_info") or result.get("stateInfo") or {}, lang)
    else:
        state_snapshot = None

    runtime_snapshot = None
    try:
        from .runtime_service import _mental_state_summary

        runtime_snapshot = _normalize_mental_snapshot(_mental_state_summary(lang))
    except Exception:
        runtime_snapshot = None

    diagnosis_snapshot = _diagnosis_mental_snapshot(lang, session_workspace=session_workspace)

    if _has_meaningful_mental_snapshot(state_snapshot):
        chosen = _merge_diagnosis_mental_snapshot(state_snapshot, diagnosis_snapshot)
        _record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="state",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return chosen
    if _has_meaningful_mental_snapshot(runtime_snapshot):
        chosen = _merge_diagnosis_mental_snapshot(runtime_snapshot, diagnosis_snapshot)
        _record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="runtime",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return chosen
    if _has_meaningful_mental_snapshot(diagnosis_snapshot):
        _record_mental_snapshot_selection(
            session_id=session_id,
            turn_id=turn_id,
            chosen_source="diagnosis",
            explicit=explicit,
            state_snapshot=state_snapshot,
            runtime_snapshot=runtime_snapshot,
            diagnosis_snapshot=diagnosis_snapshot,
        )
        return diagnosis_snapshot
    _record_mental_snapshot_selection(
        session_id=session_id,
        turn_id=turn_id,
        chosen_source="none",
        explicit=explicit,
        state_snapshot=state_snapshot,
        runtime_snapshot=runtime_snapshot,
        diagnosis_snapshot=diagnosis_snapshot,
    )
    return None


def _merge_diagnosis_mental_snapshot(
    snapshot: dict[str, Any] | None,
    diagnosis_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not snapshot:
        return None
    merged = dict(snapshot)
    if diagnosis_snapshot:
        for key in ("intervention", "metrics", "historyTail"):
            if diagnosis_snapshot.get(key):
                merged[key] = diagnosis_snapshot[key]
        if not merged.get("cognitiveState"):
            merged["cognitiveState"] = diagnosis_snapshot.get("cognitiveState", "")
        if not merged.get("confidence"):
            merged["confidence"] = diagnosis_snapshot.get("confidence", 0.0)
        if not merged.get("sampleSize"):
            merged["sampleSize"] = diagnosis_snapshot.get("sampleSize", 0)
        if not merged.get("interventionCount"):
            merged["interventionCount"] = diagnosis_snapshot.get("interventionCount", 0)
    return _normalize_mental_snapshot(merged)


def _record_mental_snapshot_selection(
    *,
    session_id: str,
    turn_id: str,
    chosen_source: str,
    explicit: dict[str, Any] | None,
    state_snapshot: dict[str, Any] | None,
    runtime_snapshot: dict[str, Any] | None,
    diagnosis_snapshot: dict[str, Any] | None,
) -> None:
    if not session_id and not turn_id:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "mental_snapshot",
            "conversation.mental_snapshot.selected",
            message="Conversation mental snapshot source selected.",
            level="info",
            outcome="selected",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "chosenSource": str(chosen_source or "").strip() or "none",
                "hasExplicit": _has_meaningful_mental_snapshot(explicit),
                "hasStateSnapshot": _has_meaningful_mental_snapshot(state_snapshot),
                "hasRuntimeSnapshot": _has_meaningful_mental_snapshot(runtime_snapshot),
                "hasDiagnosisSnapshot": _has_meaningful_mental_snapshot(diagnosis_snapshot),
                "explicitSource": str((explicit or {}).get("source") or "").strip(),
                "stateMood": str((state_snapshot or {}).get("mood") or "").strip(),
                "runtimeMood": str((runtime_snapshot or {}).get("mood") or "").strip(),
                "diagnosisState": str((diagnosis_snapshot or {}).get("cognitiveState") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _diagnosis_mental_snapshot(lang: str, *, session_workspace: str | Path | None = None) -> dict[str, Any] | None:
    try:
        from core.infrastructure.mental_model import get_mental_model

        workspace_root = Path(session_workspace).resolve() if session_workspace else (PROJECT_ROOT / "workspace")
        mental_model = get_mental_model(workspace_root=str(workspace_root))
        diagnosis = mental_model.diagnose()
        history = []
        try:
            history = mental_model.get_diagnosis_history(limit=5)
        except Exception:
            history = []
    except Exception:
        return None

    metrics = getattr(diagnosis, "metrics", {}) or {}
    cognitive_state = str(getattr(diagnosis, "state", "") or "").strip()
    intervention = trim_lines(getattr(diagnosis, "intervention", "") or "", max_lines=8)
    history_tail = [
        {
            "cognitiveState": str(getattr(item, "state", "") or "").strip(),
            "confidence": _coerce_confidence(getattr(item, "confidence", 0.0)),
            "timestamp": str(getattr(item, "timestamp", "") or "").strip(),
        }
        for item in list(history or [])[-5:]
    ]
    return _normalize_mental_snapshot({
        "mood": "",
        "feeling": "",
        "whisper": "",
        "summary": _mental_diagnosis_summary(lang, cognitive_state) if cognitive_state else "",
        "cognitiveState": cognitive_state,
        "confidence": _coerce_confidence(getattr(diagnosis, "confidence", 0.0)),
        "sampleSize": metrics.get("sample_size") or 0,
        "interventionCount": metrics.get("intervention_count") or 0,
        "updatedAt": str(getattr(diagnosis, "timestamp", "") or "").strip(),
        "source": "diagnosis",
        "intervention": intervention,
        "metrics": metrics,
        "historyTail": history_tail,
    })


def _mental_diagnosis_summary(lang: str, cognitive_state: str) -> str:
    labels = {
        "normal": text_for(lang, zh="心智诊断稳定。", en="Mental diagnosis is stable."),
        "productive": text_for(lang, zh="心智诊断显示当前推进顺畅。", en="Mental diagnosis shows productive progress."),
        "looping": text_for(lang, zh="心智诊断检测到重复循环。", en="Mental diagnosis detected looping."),
        "thrashing": text_for(lang, zh="心智诊断检测到工具或方案失稳。", en="Mental diagnosis detected thrashing."),
        "tunnel_vision": text_for(lang, zh="心智诊断检测到隧道视野。", en="Mental diagnosis detected tunnel vision."),
        "disoriented": text_for(lang, zh="心智诊断检测到方向分散。", en="Mental diagnosis detected disorientation."),
    }
    return labels.get(str(cognitive_state or "").strip().lower(), str(cognitive_state or "").strip())


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


def _build_live_output_message(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        turn_id = _live_assistant_overlay_turn_id(session_id, state.turn_id)
        stage = str(state.stage or "").strip()
        thought = str(state.thought or "").strip()
        content = str(state.content or "").strip()
        mental_snapshot = _normalize_mental_snapshot(state.mental_snapshot)
        tool_calls = _normalize_message_tool_calls(state.tool_calls)
        feedback_events = _normalize_message_feedback_events(state.feedback_events)
        timestamp = str(state.updated_at or "").strip() or _now_timestamp()
    if not thought and not content and mental_snapshot is None and not tool_calls and not feedback_events:
        return None
    message: dict[str, Any] = {
        "id": _live_assistant_message_id(session_id, turn_id),
        "role": "assistant",
        "content": content,
        "timestamp": timestamp,
        "streaming": True,
        "metadata": {
            "kind": "session_live_overlay",
            "turnId": turn_id,
            "ledgerSeq": _session_ledger_sequence(session_id),
        },
    }
    if stage:
        message["streamStage"] = stage
    if thought:
        message["thought"] = thought
    if mental_snapshot is not None:
        message["mentalSnapshot"] = mental_snapshot
    if tool_calls:
        message["toolCalls"] = tool_calls
    if feedback_events:
        message["feedbackEvents"] = feedback_events
    timeline_items = _build_message_timeline_items(
        message_id=message["id"],
        content=content,
        feedback_events=feedback_events,
        streaming=True,
        include_assistant_text=not any(
            str(event.get("kind") or "").strip() == "assistant_text"
            for event in feedback_events
        ),
    )
    if timeline_items:
        message["timelineItems"] = timeline_items
    codex_transcript = _build_codex_transcript_projection(
        message_id=message["id"],
        content=content,
        feedback_events=feedback_events,
        tool_calls=tool_calls,
        streaming=True,
    )
    if codex_transcript:
        message["codexTranscript"] = codex_transcript
    return message


def _set_session_live_output(
    session_id: str,
    *,
    turn_id: str = "",
    stage: Any = _UNSET,
    thought: Any = _UNSET,
    content: Any = _UNSET,
    mental_snapshot: Any = _UNSET,
    tool_calls: Any = _UNSET,
    feedback_events: Any = _UNSET,
    context_composition: Any = _UNSET,
    llm_payload_trace: Any = _UNSET,
) -> None:
    requested_turn_id = str(turn_id or "").strip()
    assistant_delta_state: SessionLiveOutputState | None = None
    checkpoint_snapshot: SessionLiveOutputState | None = None
    delete_checkpoint = False
    feedback_events_changed = feedback_events is not _UNSET
    # Live progress, assistant text, and tool updates already have a bounded
    # assistant_delta projection. Rebuilding the full session detail for each
    # of those updates blocks the Agent worker before the next LLM invocation.
    # Keep full snapshots for diagnostic structures that must immediately
    # reshape the visible session.  LLM payload trace is already available
    # from the in-memory live state and is persisted in the bounded checkpoint;
    # hydrating a full session detail here blocks the Agent worker before each
    # provider request.  Terminal persistence and reconnect paths still publish
    # the authoritative detail snapshot.
    publish_full_snapshot = mental_snapshot is not _UNSET
    with _RUNNING_SESSIONS_LOCK:
        current_turn_id = _SESSION_ACTIVE_TURN_IDS.get(session_id, "")
    if requested_turn_id and current_turn_id and requested_turn_id != current_turn_id:
        return
    output_turn_id = requested_turn_id or current_turn_id
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            _SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and state.turn_id and state.turn_id != output_turn_id:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            _SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and not state.turn_id:
            state.turn_id = output_turn_id
        previous_thought = state.thought
        previous_content = state.content
        if stage is not _UNSET:
            state.stage = str(stage or "").strip()
        if thought is not _UNSET:
            state.thought = _sanitize_thought_text(thought)
        if content is not _UNSET:
            state.content = _sanitize_message_content("assistant", content)
        thought_delta = ""
        content_delta = ""
        replace_thought = False
        replace_content = False
        if thought is not _UNSET:
            thought_delta, replace_thought = _live_output_delta(previous_thought, state.thought)
        if content is not _UNSET:
            content_delta, replace_content = _live_output_delta(previous_content, state.content)
        if mental_snapshot is not _UNSET:
            state.mental_snapshot = _normalize_mental_snapshot(mental_snapshot)
        if tool_calls is not _UNSET:
            state.tool_calls = _normalize_message_tool_calls(tool_calls)
        if feedback_events is not _UNSET:
            state.feedback_events = _normalize_message_feedback_events(feedback_events)
        if context_composition is not _UNSET:
            state.context_composition = _normalize_session_context_composition(context_composition)
        if llm_payload_trace is not _UNSET:
            state.llm_payload_trace = _normalize_session_llm_payload_trace(llm_payload_trace)
        state.updated_at = _now_timestamp()
        if (
            not state.thought
            and not state.content
            and state.mental_snapshot is None
            and not state.tool_calls
            and not state.feedback_events
            and state.context_composition is None
            and state.llm_payload_trace is None
        ):
            if content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET:
                assistant_delta_state = SessionLiveOutputState(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    stage=state.stage,
                    thought=state.thought,
                    content=state.content,
                    thought_delta=thought_delta,
                    content_delta=content_delta,
                    replace_thought=replace_thought,
                    replace_content=replace_content,
                    feedback_events=list(state.feedback_events or []),
                    updated_at=state.updated_at,
                )
            _SESSION_LIVE_OUTPUTS.pop(session_id, None)
            delete_checkpoint = True
        elif content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET or tool_calls is not _UNSET:
            assistant_delta_state = SessionLiveOutputState(
                session_id=state.session_id,
                turn_id=state.turn_id,
                stage=state.stage,
                thought=state.thought,
                content=state.content,
                thought_delta=thought_delta,
                content_delta=content_delta,
                replace_thought=replace_thought,
                replace_content=replace_content,
                tool_calls=list(state.tool_calls or []),
                feedback_events=list(state.feedback_events or []),
                updated_at=state.updated_at,
            )
        if state.turn_id and (
            content is not _UNSET
            or thought is not _UNSET
            or tool_calls is not _UNSET
            or feedback_events is not _UNSET
            or mental_snapshot is not _UNSET
            or llm_payload_trace is not _UNSET
        ):
            checkpoint_snapshot = SessionLiveOutputState(
                session_id=state.session_id,
                turn_id=state.turn_id,
                stage=state.stage,
                thought=state.thought,
                content=state.content,
                mental_snapshot=dict(state.mental_snapshot or {}) if isinstance(state.mental_snapshot, dict) else None,
                tool_calls=list(state.tool_calls or []),
                feedback_events=list(state.feedback_events or []),
                context_composition=dict(state.context_composition or {}) if isinstance(state.context_composition, dict) else None,
                llm_payload_trace=dict(state.llm_payload_trace or {}) if isinstance(state.llm_payload_trace, dict) else None,
                updated_at=state.updated_at,
            )
    if delete_checkpoint:
        _delete_session_live_output_checkpoint(session_id)
    elif checkpoint_snapshot is not None:
        _write_session_live_output_checkpoint(session_id, checkpoint_snapshot)
    if assistant_delta_state is not None:
        _publish_session_assistant_delta(
            session_id,
            assistant_delta_state,
            include_feedback_events=feedback_events_changed,
        )
    if publish_full_snapshot:
        _publish_session_detail_snapshot(session_id)


def _append_session_live_feedback_event(session_id: str, event: dict[str, Any], *, turn_id: str = "") -> list[dict[str, Any]]:
    requested_turn_id = str(turn_id or "").strip()
    with _RUNNING_SESSIONS_LOCK:
        current_turn_id = _SESSION_ACTIVE_TURN_IDS.get(session_id, "")
    if requested_turn_id and current_turn_id and requested_turn_id != current_turn_id:
        return []
    output_turn_id = requested_turn_id or current_turn_id
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            _SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and state.turn_id and state.turn_id != output_turn_id:
            state = SessionLiveOutputState(session_id=session_id, turn_id=output_turn_id)
            _SESSION_LIVE_OUTPUTS[session_id] = state
        elif output_turn_id and not state.turn_id:
            state.turn_id = output_turn_id
        sequence = max((_coerce_nonnegative_int(item.get("sequence")) for item in state.feedback_events), default=0) + 1
        entry = {
            "sequence": sequence,
            "timestamp": _now_timestamp(),
            **event,
        }
        duplicate_index = -1
        if str(entry.get("kind") or "").strip() == "status":
            name = str(entry.get("name") or "").strip()
            state.feedback_events = _close_previous_running_status_events(state.feedback_events, name)
            for index, existing in enumerate(state.feedback_events):
                if existing.get("kind") == "status" and str(existing.get("name") or "").strip() == name:
                    duplicate_index = index
                    break
        if duplicate_index >= 0:
            previous = dict(state.feedback_events[duplicate_index])
            state.feedback_events[duplicate_index] = {
                **previous,
                **entry,
                "sequence": previous.get("sequence") or entry["sequence"],
            }
        else:
            state.feedback_events.append(entry)
        state.feedback_events = _normalize_message_feedback_events(state.feedback_events)[-120:]
        state.updated_at = _now_timestamp()
        return list(state.feedback_events)


def _set_session_live_context_composition(
    session_id: str,
    context_composition: Any,
    *,
    turn_id: str = "",
) -> None:
    _set_session_live_output(session_id, turn_id=turn_id, context_composition=context_composition)


def _set_session_llm_payload_trace_live_output(
    session_id: str,
    trace: Any,
    *,
    turn_id: str = "",
) -> None:
    _set_session_live_output(session_id, turn_id=turn_id, llm_payload_trace=trace)


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




def _touch_chat_turn_work_run(
    *,
    session_id: str,
    turn_id: str,
    stage: str,
    summary: str = "",
    last_tool_error: dict[str, Any] | None = None,
) -> None:
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return
    previous = _WORK_RUN_STORE.load_snapshot("chat_turn", normalized_turn_id)
    if not isinstance(previous, dict):
        return
    status = str(previous.get("status") or previous.get("currentPhase") or "running").strip().lower() or "running"
    if status not in {"queued", "running", "stopping", "paused"}:
        return
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=normalized_turn_id,
        status=status,
        summary=summary or str(previous.get("summary") or "").strip(),
        updated_at=_now_timestamp(),
        last_tool_error=last_tool_error,
    )


def _set_session_waiting_live_output(session_id: str, *, turn_id: str = "") -> None:
    _set_session_turn_progress_live_output(session_id, "context_prepare", turn_id=turn_id)


def _set_session_turn_progress_live_output(session_id: str, stage: str, *, turn_id: str = "") -> None:
    language = get_web_language()
    stage_key = str(stage or "").strip().lower()
    labels = {
        "context_prepare": text_for(
            language,
            zh="正在准备对话上下文...\n正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
            en="Preparing the conversation context...\nReading the current session, bound Agent, tool policy, and any resumable turn state.",
        ),
        "queued": text_for(
            language,
            zh="当前会话或 Agent 并发槽暂满，本轮已进入队列...\n会在同会话任务结束或 Agent 释放并发槽后继续执行。",
            en="This session or Agent concurrency slot is busy. This turn is queued...\nIt will continue when the session finishes or the Agent releases a concurrency slot.",
        ),
        "agent_prepare": text_for(
            language,
            zh="正在唤起对话 agent...\n正在绑定 Agent 实例、私有工作区、记忆根和工具工作区。",
            en="Preparing the conversation agent...\nBinding the Agent instance, private workspace, memory root, and tool workspace.",
        ),
        "history_restore": text_for(
            language,
            zh="正在恢复上一轮对话记忆...\n会把可继续的任务现场接回本轮上下文。",
            en="Restoring the previous conversation memory...\nReattaching resumable task state to this turn context.",
        ),
        "model_request": text_for(
            language,
            zh="正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。",
            en="Requesting the model and waiting for the first response chunk...\nThe context is assembled and the LLM call is starting.",
        ),
        "model_thinking": text_for(
            language,
            zh="正在思考中，等待模型输出...\n模型请求已发出，服务端可能正在推理，正文会在生成后显示。",
            en="Thinking and waiting for model output...\nThe model request has been sent; server-side reasoning may be running and visible text will appear after generation.",
        ),
        "followup_prepare": text_for(
            language,
            zh="正在准备继续推进下一步...\n会沿用上一轮 active task 继续收口。",
            en="Preparing the next continuation step...\nContinuing from the previous active task.",
        ),
    }
    content = labels.get(
        stage_key,
        text_for(
            language,
            zh="正在等待模型响应...\n当前阶段还没有更细的前端状态说明。",
            en="Waiting for the model response...\nNo more detailed frontend progress is available for this stage yet.",
        ),
    )
    feedback_events = _append_session_live_feedback_event(
        session_id,
        {
            "kind": "status",
            "status": "running",
            "name": stage_key or "waiting",
            "summary": trim_lines(content, max_lines=2),
            "resultPreview": content,
        },
        turn_id=turn_id,
    )
    capture = _active_session_turn_capture(session_id, turn_id)
    if capture is not None:
        capture.note_status_event(stage_key or "waiting", content, status="running", name=stage_key or "waiting")
        feedback_events = list(capture.feedback_events)
    _set_session_live_output(
        session_id,
        turn_id=turn_id,
        stage=stage_key,
        feedback_events=feedback_events,
    )
    # Cosmetic progress is already checkpointed by the live-output channel.  Keep
    # durable WorkRun writes for retry/failure/tool-error and terminal transitions.
    _record_session_turn_lifecycle_event(
        session_id,
        f"ui_progress_{stage_key or 'waiting'}",
        turn_id=turn_id,
        outcome="running",
        fields={
            "progressStage": stage_key,
            "messageLength": len(content),
        },
    )


def _set_session_llm_status_live_output(
    session_id: str,
    status: str,
    *,
    turn_id: str = "",
    fields: dict[str, Any] | None = None,
) -> None:
    language = get_web_language()
    status_key = str(status or "").strip().lower()
    data = fields if isinstance(fields, dict) else {}
    attempt = _coerce_nonnegative_int(data.get("attempt"))
    max_attempts = _coerce_nonnegative_int(data.get("max_attempts") or data.get("maxAttempts"))
    category = str(data.get("category") or data.get("reason") or "").strip()
    close_code = _coerce_nonnegative_int(data.get("closeCode") or data.get("close_code"))
    close_reason = trim_lines(str(data.get("closeReason") or data.get("close_reason") or "").strip(), max_lines=1)
    fallback_transport = str(data.get("fallbackTransport") or data.get("fallback_transport") or "").strip()
    transport_detail = close_reason or (f"WebSocket {close_code}" if close_code else "")
    feedback_status = "running"
    feedback_name = status_key or "status"
    feedback_error = ""
    failure_class = ""

    if status_key == "retrying":
        attempt_line = (
            text_for(language, zh=f"第 {attempt}/{max_attempts} 次", en=f"attempt {attempt}/{max_attempts}")
            if attempt and max_attempts
            else text_for(language, zh="正在重试", en="retrying")
        )
        reason_line = category or text_for(language, zh="上游连接暂时不稳定", en="temporary upstream connection issue")
        content = text_for(
            language,
            zh=f"模型连接正在重试...\n{attempt_line}；原因：{reason_line}。本轮仍在继续，请不要重复提交。",
            en=f"Retrying the model connection...\n{attempt_line}; reason: {reason_line}. This turn is still running.",
        )
        stage = "model_retry"
    elif status_key == "transport_degraded":
        content = text_for(
            language,
            zh="模型连接中断，正在恢复。",
            en="The model connection was interrupted and is recovering.",
        )
        stage = "model_transport"
        feedback_status = "degraded"
        feedback_name = "model_transport"
        feedback_error = transport_detail or category
        failure_class = category or "provider_transport_unavailable"
    elif status_key == "transport_fallback":
        target = fallback_transport.upper() if fallback_transport else "HTTP"
        content = text_for(
            language,
            zh=f"WebSocket 暂时不可用，正在切换到 {target}。",
            en=f"WebSocket is temporarily unavailable; switching to {target}.",
        )
        stage = "model_transport"
        feedback_status = "degraded"
        feedback_name = "model_transport"
        feedback_error = transport_detail or category
        failure_class = category or "provider_transport_unavailable"
    elif status_key == "transport_recovered":
        target = fallback_transport.upper() if fallback_transport else "HTTP"
        content = text_for(
            language,
            zh=f"连接已恢复。\n已从 WebSocket 切换到 {target}。",
            en=f"Connection recovered.\nSwitched from WebSocket to {target}.",
        )
        stage = "model_transport"
        feedback_status = "recovered"
        feedback_name = "model_transport"
    elif status_key == "failed":
        reason_line = category or text_for(language, zh="模型调用失败", en="model call failed")
        hint_line = (
            text_for(language, zh="\n请检查网络连接或代理端口是否可用。", en="\nCheck the network connection or proxy port.")
            if category == "network_error"
            else ""
        )
        content = text_for(
            language,
            zh=f"模型请求失败。\n原因：{reason_line}。{hint_line}",
            en=f"The model request failed.\nReason: {reason_line}.{hint_line}",
        )
        stage = "model_failed"
        feedback_status = "failed"
    else:
        return

    feedback_event = {
        "kind": "status",
        "status": feedback_status if status_key != "failed" else "failed",
        "name": feedback_name,
        "summary": trim_lines(content, max_lines=2),
        "resultPreview": content,
        "error": feedback_error,
        "failureClass": failure_class,
        "transportStatus": status_key if status_key.startswith("transport_") else "",
    }
    feedback_events = _append_session_live_feedback_event(
        session_id,
        feedback_event,
        turn_id=turn_id,
    )
    capture = _active_session_turn_capture(session_id, turn_id)
    if capture is not None:
        capture.note_status_event(
            status_key or stage,
            content,
            status="failed" if status_key == "failed" else "running",
            name=feedback_name,
        )
        for existing in capture.feedback_events:
            if existing.get("kind") == "status" and str(existing.get("name") or "").strip() == feedback_name:
                existing.update(feedback_event)
                break
        feedback_events = list(capture.feedback_events)
    live_output_fields: dict[str, Any] = {
        "turn_id": turn_id,
        "stage": stage,
        "feedback_events": feedback_events,
    }
    if not status_key.startswith("transport_"):
        live_output_fields["content"] = content
    _set_session_live_output(session_id, **live_output_fields)
    _touch_chat_turn_work_run(session_id=session_id, turn_id=turn_id, stage=stage, summary=trim_lines(content, max_lines=1))
    _record_session_turn_lifecycle_event(
        session_id,
        f"llm_status_{status_key}",
        turn_id=turn_id,
        outcome="running" if status_key != "failed" else "failed",
        fields={
            "llmStatus": status_key,
            "attempt": attempt,
            "maxAttempts": max_attempts,
            "category": trim_lines(category, max_lines=1),
            "closeCode": close_code,
            "closeReason": close_reason,
            "fallbackTransport": fallback_transport,
            "messageLength": len(content),
        },
    )


def _set_session_model_thinking_live_output(session_id: str, *, turn_id: str = "", thought_chars: int = 0) -> None:
    live_state = _snapshot_session_live_output(session_id)
    if live_state is not None and str(live_state.stage or "").strip() == "model_thinking":
        return
    _set_session_turn_progress_live_output(session_id, "model_thinking", turn_id=turn_id)
    event_status = "reasoning" if max(0, int(thought_chars or 0)) > 0 else "server_thinking"
    _record_session_turn_lifecycle_event(
        session_id,
        "llm_status_reasoning" if event_status == "reasoning" else "llm_status_server_thinking",
        turn_id=turn_id,
        outcome="running",
        fields={
            "llmStatus": event_status,
            "thoughtChars": max(0, int(thought_chars or 0)),
        },
    )


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


def _record_session_chat_review_candidate_event(
    phase: str,
    *,
    session_id: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "chat_review",
            f"session_candidate_{phase}",
            f"chat_review.session_candidate.{phase}",
            level=level,
            outcome=outcome,
            message="Session chat review candidate event.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "source": "manual_session_action",
                **(fields or {}),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-chat-review.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "phase": phase,
                "outcome": outcome,
                **(fields or {}),
            },
        )
    except Exception:
        return


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
