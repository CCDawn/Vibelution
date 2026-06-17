"""Real chat session payloads for the web workbench."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import queue
import re
import secrets
import shutil
import threading
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config.settings import get_config
from config.settings import get_web_chat_config
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
    EVENT_ASSISTANT_MESSAGE,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
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
    latest_ledger_sequence,
    latest_open_turn_id,
    load_conversation_events,
)
from core.chat.context_assembler import assemble_conversation_context
from core.chat.skill_registry import build_skill_runtime_context, skill_descriptor_for_log
from core.chat.slash_commands import SkillSlashCommand, parse_skill_slash_command
from core.infrastructure import developer_sandbox
from core.infrastructure.event_bus import EventNames, get_event_bus
from core.llm.client import llm_status_context
from core.llm.payload_builder import prompt_cache_partition_scope
from core.llm.agent_runtime import (
    AgentLlmResolutionError,
    resolve_agent_llm,
)
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
    sanitize_assistant_thought_text,
    sanitize_assistant_visible_text,
)
from core.orchestration.context_engine import build_agent_context, record_agent_turn_result
from core.orchestration.turn_runner import (
    call_agent_factory_with_supported_kwargs,
    create_agent_runtime,
    run_existing_agent_single_turn,
)
from core.runtime_manager.evolution_store import load_active_run_snapshot as load_evolution_active_run_snapshot
from core.runtime_manager.work_run_leases import (
    MEMORY_WRITE_LEASE,
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
from .i18n import get_web_language, text_for
from .model_capability_service import model_record_image_input_support
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
    resolve_memory_policy_for_agent,
    update_agent_instance,
)
from .runtime_scene_service import record_runtime_scene_conversation_event, record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CHAT_STATE_LOCK = threading.RLock()
_RUNNING_SESSIONS_LOCK = threading.Lock()
_RUNNING_SESSION_IDS: set[str] = set()
_SESSION_ACTIVE_TURN_IDS: dict[str, str] = {}
_SESSION_ACTIVE_TURN_LEASES: dict[str, list[str]] = {}
_SESSION_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-chat-turn")
_SESSION_AGENT_MAX_ACTIVE_TURNS = 4
_SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_SESSION_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_SESSION_STREAM_HEARTBEAT_SECONDS = 15.0
_SESSION_STREAM_QUEUE_SIZE = 8
_SESSION_STREAM_COALESCED_EVENT_TYPES = {"session_detail", "assistant_delta"}
_SESSION_STREAM_BUSY_PHASES = {"queued", "running", "stopping", "paused"}
_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS = 0.75
_SESSION_STREAM_LAST_SNAPSHOT_LOCK = threading.Lock()
_SESSION_STREAM_LAST_SNAPSHOT_AT: dict[str, float] = {}
_SESSION_STREAM_THROTTLED_COUNTS: dict[str, int] = {}
_SESSION_TURN_CONTROLS_LOCK = threading.Lock()
_SESSION_TURN_CONTROLS: dict[str, "SessionTurnControl"] = {}
_SESSION_LIVE_OUTPUTS_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUTS: dict[str, "SessionLiveOutputState"] = {}
_SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT: dict[str, float] = {}
_SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS = 0.75
_SESSION_UI_CAPTURE_LOCK = threading.Lock()
_SESSION_UI_CAPTURE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_session_ui_capture_context",
    default={},
)
_SESSION_LIST_CACHE_LOCK = threading.Lock()
_SESSION_LIST_CACHE_CONDITION = threading.Condition(_SESSION_LIST_CACHE_LOCK)
_SESSION_LIST_CACHE_TTL_SECONDS = 4.0
_SESSION_LIST_CACHE: dict[str, Any] = {}
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


def _session_list_source_signature() -> tuple[Any, ...]:
    """Return cheap file signatures for the read-only session index inputs."""

    def signature(path: Path) -> tuple[str, int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path), -1, -1)
        return (str(path), int(stat.st_mtime_ns), int(stat.st_size))

    inbox_signatures: list[tuple[str, tuple[str, bool, int, int]]] = []
    state = agent_directory_service.load_state()
    agents = list(state.get("agents") or []) if isinstance(state, dict) else []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        inbox_path = agent_directory_service._agent_workspace_event_path(
            agent,
            "agent_inbox_messages.jsonl",
        )
        inbox_signatures.append(
            (
                agent_id,
                agent_directory_service._jsonl_signature(inbox_path),
            )
        )

    return (
        signature(chat_state_path(PROJECT_ROOT)),
        signature(agent_directory_service.registry_path()),
        tuple(inbox_signatures),
    )


def _copy_session_list_snapshot(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_copy_session_summary_snapshot(item) for item in sessions if isinstance(item, dict)]


def _copy_session_summary_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(item)
    child_session_ids = snapshot.get("childSessionIds")
    if isinstance(child_session_ids, list):
        snapshot["childSessionIds"] = list(child_session_ids)
    result_card = snapshot.get("resultCard")
    if isinstance(result_card, dict):
        copied_card = dict(result_card)
        changed_files = copied_card.get("changedFiles")
        if isinstance(changed_files, list):
            copied_card["changedFiles"] = list(changed_files)
        validations = copied_card.get("validations")
        if isinstance(validations, list):
            copied_card["validations"] = list(validations)
        snapshot["resultCard"] = copied_card
    return snapshot


def _get_session_list_cache(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    with _SESSION_LIST_CACHE_LOCK:
        snapshot = _SESSION_LIST_CACHE.get("sessions")
        if not isinstance(snapshot, list):
            return None
        if _SESSION_LIST_CACHE.get("signature") != signature:
            return None
        cached_at = _SESSION_LIST_CACHE.get("cached_at")
        try:
            cache_age_seconds = now - float(cached_at)
        except (TypeError, ValueError):
            return None
        if cache_age_seconds < 0:
            return None
        if not allow_stale_matching_signature and cache_age_seconds > _SESSION_LIST_CACHE_TTL_SECONDS:
            return None
        return (
            _copy_session_list_snapshot(snapshot),
            int(round(cache_age_seconds * 1000)),
            int(_SESSION_LIST_CACHE.get("conversation_count") or 0),
            int(_SESSION_LIST_CACHE.get("agent_count") or 0),
        )


def _get_session_list_cache_locked(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[list[dict[str, Any]], int, int, int] | None:
    snapshot = _SESSION_LIST_CACHE.get("sessions")
    if not isinstance(snapshot, list):
        return None
    if _SESSION_LIST_CACHE.get("signature") != signature:
        return None
    cached_at = _SESSION_LIST_CACHE.get("cached_at")
    try:
        cache_age_seconds = now - float(cached_at)
    except (TypeError, ValueError):
        return None
    if cache_age_seconds < 0:
        return None
    if not allow_stale_matching_signature and cache_age_seconds > _SESSION_LIST_CACHE_TTL_SECONDS:
        return None
    return (
        _copy_session_list_snapshot(snapshot),
        int(round(cache_age_seconds * 1000)),
        int(_SESSION_LIST_CACHE.get("conversation_count") or 0),
        int(_SESSION_LIST_CACHE.get("agent_count") or 0),
    )


def _begin_session_list_cache_build(
    *,
    now: float,
    signature: tuple[Any, ...],
    allow_stale_matching_signature: bool = False,
) -> tuple[tuple[list[dict[str, Any]], int, int, int] | None, bool, bool]:
    """Return cached sessions or reserve this caller as the index builder."""

    waited_for_inflight = False
    with _SESSION_LIST_CACHE_CONDITION:
        cached = _get_session_list_cache_locked(
            now=now,
            signature=signature,
            allow_stale_matching_signature=allow_stale_matching_signature,
        )
        if cached is not None:
            return cached, False, waited_for_inflight
        while _SESSION_LIST_CACHE.get("inflight_signature") == signature:
            waited_for_inflight = True
            _SESSION_LIST_CACHE_CONDITION.wait(timeout=10.0)
            cached = _get_session_list_cache_locked(
                now=_perf_counter(),
                signature=signature,
                allow_stale_matching_signature=allow_stale_matching_signature,
            )
            if cached is not None:
                return cached, False, waited_for_inflight
            if _SESSION_LIST_CACHE.get("inflight_signature") != signature:
                break
        _SESSION_LIST_CACHE["inflight_signature"] = signature
        return None, True, waited_for_inflight


def _finish_session_list_cache_build(
    *,
    signature: tuple[Any, ...],
    sessions: list[dict[str, Any]] | None = None,
    started_at: float | None = None,
    conversation_count: int = 0,
    agent_count: int = 0,
) -> None:
    with _SESSION_LIST_CACHE_CONDITION:
        if sessions is not None and started_at is not None:
            _SESSION_LIST_CACHE.clear()
            _SESSION_LIST_CACHE.update(
                {
                    "sessions": _copy_session_list_snapshot(sessions),
                    "cached_at": started_at,
                    "signature": signature,
                    "conversation_count": int(conversation_count),
                    "agent_count": int(agent_count),
                }
            )
        elif _SESSION_LIST_CACHE.get("inflight_signature") == signature:
            _SESSION_LIST_CACHE.pop("inflight_signature", None)
        _SESSION_LIST_CACHE_CONDITION.notify_all()


def _set_session_list_cache(
    sessions: list[dict[str, Any]],
    *,
    now: float,
    signature: tuple[Any, ...],
    conversation_count: int,
    agent_count: int,
) -> None:
    with _SESSION_LIST_CACHE_LOCK:
        _SESSION_LIST_CACHE.clear()
        _SESSION_LIST_CACHE.update(
            {
                "sessions": _copy_session_list_snapshot(sessions),
                "cached_at": now,
                "signature": signature,
                "conversation_count": int(conversation_count),
                "agent_count": int(agent_count),
            }
        )


def _invalidate_session_list_cache() -> None:
    global _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE
    with _SESSION_LIST_CACHE_CONDITION:
        _SESSION_LIST_CACHE.clear()
        _SESSION_LIST_CACHE_CONDITION.notify_all()
    with _DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        _DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((_perf_counter() - started_at) * 1000)))


def _elapsed_ms_between(started_at: Any, ended_at: float | None = None) -> int:
    try:
        start_value = float(started_at)
    except (TypeError, ValueError):
        return 0
    end_value = _perf_counter() if ended_at is None else float(ended_at)
    return max(0, int(round((end_value - start_value) * 1000)))
_IMAGE_ATTACHMENT_VISION_PATTERNS = (
    "分析",
    "识别",
    "看看",
    "看一下",
    "看下",
    "看图",
    "这是什么",
    "是什么",
    "有什么",
    "描述",
    "解释",
    "读图",
    "提取",
    "文字",
    "ocr",
    "identify",
    "analyze",
    "analyse",
    "describe",
    "what is",
    "what's",
    "read",
    "extract",
)
_IMAGE_ATTACHMENT_IMAGE2_EXPLICIT_PATTERNS = (
    "生成",
    "画一张",
    "帮我画",
    "画成",
    "绘制",
    "重绘",
    "改成",
    "改为",
    "修改",
    "改一下",
    "调整",
    "换风格",
    "做头像",
    "create",
    "generate",
    "draw",
    "redraw",
    "edit",
    "restyle",
    "make",
)
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


def _safe_session_workspace_token(session_id: str) -> str:
    raw = str(session_id or "").strip()
    token = _SESSION_WORKSPACE_SAFE_CHARS.sub("-", raw).strip("._-")
    if not token:
        token = "session"
    if token != raw or len(token) > 96:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        token = f"{token[:84].rstrip('._-') or 'session'}-{digest}"
    return token


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
    return {
        "schemaVersion": 1,
        "sessionId": str(getattr(state, "session_id", "") or "").strip(),
        "turnId": str(getattr(state, "turn_id", "") or "").strip(),
        "stage": str(getattr(state, "stage", "") or "").strip(),
        "content": str(getattr(state, "content", "") or ""),
        "thought": str(getattr(state, "thought", "") or ""),
        "mentalSnapshot": _normalize_mental_snapshot(getattr(state, "mental_snapshot", None)),
        "toolCalls": _normalize_message_tool_calls(getattr(state, "tool_calls", []) or []),
        "feedbackEvents": _normalize_message_feedback_events(getattr(state, "feedback_events", []) or []),
        "contextComposition": _normalize_session_context_composition(getattr(state, "context_composition", None)),
        "updatedAt": str(getattr(state, "updated_at", "") or "").strip() or _now_timestamp(),
    }


def _live_output_checkpoint_has_visible_payload(payload: dict[str, Any]) -> bool:
    return bool(
        str(payload.get("content") or "").strip()
        or str(payload.get("thought") or "").strip()
        or list(payload.get("toolCalls") or [])
        or list(payload.get("feedbackEvents") or [])
        or isinstance(payload.get("mentalSnapshot"), dict)
    )


def _write_session_live_output_checkpoint(
    session_id: str,
    state: "SessionLiveOutputState",
    *,
    force: bool = False,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    now = _perf_counter()
    if not force:
        with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
            last_at = _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.get(normalized_session_id, 0.0)
        if last_at > 0 and now - last_at < _SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS:
            return
    payload = _live_output_checkpoint_payload(state)
    if not _live_output_checkpoint_has_visible_payload(payload):
        if force:
            _delete_session_live_output_checkpoint(normalized_session_id)
        return
    checkpoint_path = _session_live_output_checkpoint_path(normalized_session_id)
    tmp_path = checkpoint_path.with_name(f"{checkpoint_path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(checkpoint_path)
        with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
            _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT[normalized_session_id] = now
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _delete_session_live_output_checkpoint(session_id: str) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
        _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.pop(normalized_session_id, None)
    try:
        _session_live_output_checkpoint_path(normalized_session_id).unlink(missing_ok=True)
    except OSError:
        return


def _load_session_live_output_checkpoint(session_id: str) -> "SessionLiveOutputState | None":
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    try:
        payload = json.loads(_session_live_output_checkpoint_path(normalized_session_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not _live_output_checkpoint_has_visible_payload(payload):
        return None
    return SessionLiveOutputState(
        session_id=normalized_session_id,
        turn_id=str(payload.get("turnId") or "").strip(),
        stage=str(payload.get("stage") or "").strip(),
        thought=_sanitize_thought_text(payload.get("thought") or ""),
        content=_sanitize_message_content("assistant", payload.get("content") or ""),
        mental_snapshot=_normalize_mental_snapshot(payload.get("mentalSnapshot")),
        tool_calls=_normalize_message_tool_calls(payload.get("toolCalls") or []),
        feedback_events=_normalize_message_feedback_events(payload.get("feedbackEvents") or []),
        context_composition=_normalize_session_context_composition(payload.get("contextComposition")),
        updated_at=str(payload.get("updatedAt") or "").strip(),
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
        messages = normalize_chat_messages(conversation.get("messages") or [])
        for message in reversed(messages):
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            if (
                str(message.get("role") or "").strip().lower() == "assistant"
                and str(metadata.get("turnId") or "").strip() == normalized_turn_id
            ):
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
        conversation["messages"] = messages + [assistant_entry]
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        chat_payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, chat_payload)


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
    normalized_session_id = str(session_id or "").strip()
    normalized_event_type = str(event_type or "").strip()
    if not normalized_session_id or not normalized_event_type:
        return
    try:
        append_conversation_event(
            PROJECT_ROOT,
            normalized_session_id,
            str(turn_id or "").strip(),
            normalized_event_type,
            status=status,
            payload=payload or {},
            source=source,
            visible_in_model=visible_in_model,
            projection_kind=projection_kind,
            tool_call_id=tool_call_id,
            correlation_id=correlation_id,
            source_kind=source_kind,
        )
    except Exception as exc:
        try:
            record_runtime_scene_event(
                "conversation",
                "conversation_ledger",
                "conversation.ledger.append_failed",
                level="warning",
                outcome="failed",
                message="Failed to append a chat conversation ledger event.",
                fields={
                    "sessionId": normalized_session_id,
                    "turnId": str(turn_id or "").strip(),
                    "eventType": normalized_event_type,
                    "errorType": type(exc).__name__,
                    "errorPreview": trim_lines(str(exc), max_lines=2),
                },
                lifecycle=True,
            )
        except Exception:
            return


def _reconcile_stale_session_ledger(session_id: str, *, active_turn_id: str = "", reason: str = "process_restarted") -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    try:
        events = load_conversation_events(PROJECT_ROOT, normalized_session_id)
        turn_id = latest_open_turn_id(events)
        if not turn_id:
            _delete_session_live_output_checkpoint(normalized_session_id)
            return
        if active_turn_id and turn_id == str(active_turn_id or "").strip():
            return
        checkpoint = _load_session_live_output_checkpoint(normalized_session_id)
        if checkpoint is not None and (not checkpoint.turn_id or checkpoint.turn_id == turn_id):
            payload = _live_output_checkpoint_payload(checkpoint)
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
                },
                source="recover_live_output_checkpoint",
            )
        event = append_conversation_event(
            PROJECT_ROOT,
            normalized_session_id,
            turn_id,
            EVENT_TURN_INTERRUPTED,
            status="interrupted",
            payload={
                "reason": str(reason or "process_restarted").strip() or "process_restarted",
                "marker": TURN_INTERRUPTED_MARKER,
            },
            source="session_service",
        )
        _delete_session_live_output_checkpoint(normalized_session_id)
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
                "turnId": event.turn_id,
                "reason": reason,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _session_ledger_sequence(session_id: str) -> int:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return 0
    try:
        return latest_ledger_sequence(PROJECT_ROOT, normalized_session_id)
    except Exception:
        return 0


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
    for message in reversed(list(conversation.get("messages") or [])):
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
    if _contains_any_image_attachment_intent_pattern(normalized, _RECENT_IMAGE_REFERENCE_EXACT_PATTERNS):
        return True
    has_reference = _contains_any_image_attachment_intent_pattern(normalized, _RECENT_IMAGE_REFERENCE_WORDS)
    has_image_target = _contains_any_image_attachment_intent_pattern(normalized, _RECENT_IMAGE_TARGET_WORDS)
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
    for item in reversed(list(conversation.get("messages") or [])[-8:]):
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
    intent = _classify_image_attachment_intent(str(prompt or ""))
    return intent in {"image2_edit", "vision_analysis"}


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
    if _has_recent_image_attachment_reference(value):
        return True
    image_terms = ("原图", "原来的图片", "原来的图", "图片", "图像", "画面", "image", "picture")
    retry_terms = ("逼近", "调整提示词", "继续调整", "重绘", "生成的图片", "完全不一样", "参考", "match", "reference", "retry")
    return any(term in compact for term in image_terms) and any(term in compact for term in retry_terms)


def _find_recent_user_image_attachment(conversation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(conversation, dict):
        return {}
    for message in reversed(list(conversation.get("messages") or [])):
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
        messages = normalize_chat_messages(conversation.get("messages") or [])
        assistant_entry = _make_chat_message(
            "assistant",
            content,
            tool_calls or [],
            metadata=metadata,
        )
        conversation["messages"] = messages + [assistant_entry]
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)

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


def _repair_conversation_agent_legacy_model_fields(
    conversation: dict[str, Any],
    *,
    conversation_id: str,
    agent_id: str,
    agent: dict[str, Any],
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
            prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
            role_key=str(agent.get("roleKey") or "").strip(),
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
        return changed
    existing_agent = _agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
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
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        if conversation.get("agentPrimaryDirectSessionId"):
            conversation["agentPrimaryDirectSessionId"] = ""
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
        existing_direct_session_id = str(existing_agent.get("directSessionId") or "").strip()
        if existing_direct_session_id and existing_direct_session_id != conversation_id:
            if conversation.get("agentDirectSessionMismatch") is not True:
                conversation["agentDirectSessionMismatch"] = True
                changed = True
            if conversation.get("agentPrimaryDirectSessionId") != existing_direct_session_id:
                conversation["agentPrimaryDirectSessionId"] = existing_direct_session_id
                changed = True
        else:
            if conversation.get("agentDirectSessionMismatch"):
                conversation["agentDirectSessionMismatch"] = False
                changed = True
            if conversation.get("agentPrimaryDirectSessionId"):
                conversation["agentPrimaryDirectSessionId"] = ""
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


def _sync_agent_directory_project_root() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT
        _invalidate_session_list_cache()


def _agent_lookup_for_conversations() -> dict[str, dict[str, Any]]:
    _sync_agent_directory_project_root()
    state = agent_directory_service.load_state()
    return {
        str(item.get("agentId") or "").strip(): _conversation_agent_from_state(item)
        for item in state.get("agents") or []
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    }


def _conversation_agent_from_state(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("agentId") or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
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
        "workspacePath": workspace_path,
        "avatarImagePath": avatar_path,
        "avatarImageUrl": agent_directory_service.agent_avatar_image_url(avatar_path),
        "status": str(agent.get("status") or "active").strip() or "active",
        "metadata": dict(metadata),
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
    }


def _agent_avatar_path(agent: dict[str, Any], metadata: dict[str, Any] | None = None) -> str:
    source = metadata if isinstance(metadata, dict) else agent.get("metadata")
    meta = source if isinstance(source, dict) else {}
    raw_path = str(agent.get("avatarImagePath") or meta.get("avatarImagePath") or "").strip()
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


def _session_agent_status_payload(
    agent_id: str,
    agent: dict[str, Any] | None,
    *,
    hydrate_agent: bool = True,
    agent_lookup_checked: bool = False,
    persisted_status_code: str = "",
) -> dict[str, Any]:
    normalized_agent_id = str(agent_id or "").strip()
    if str(persisted_status_code or "").strip() == "deleted_agent":
        return {
            "agentMissing": True,
            "agentStatusCode": "deleted_agent",
            "agentStatusMessage": text_for(
                get_web_language(),
                zh="缺少有效 Agent：当前会话绑定的 Agent 已被彻底删除，历史会话已保留但不会自动重建 Agent。",
                en="Missing valid Agent: the Agent bound to this session was permanently deleted; history is preserved without recreating it.",
            ),
        }
    if not normalized_agent_id:
        return {
            "agentMissing": False,
            "agentStatusCode": "",
            "agentStatusMessage": "",
        }
    if not hydrate_agent and not isinstance(agent, dict) and not agent_lookup_checked:
        return {
            "agentMissing": False,
            "agentStatusCode": "",
            "agentStatusMessage": "",
        }
    if not isinstance(agent, dict):
        return {
            "agentMissing": True,
            "agentStatusCode": "missing_agent",
            "agentStatusMessage": text_for(
                get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。",
                en="Missing valid Agent: this session references an Agent that no longer exists or is unavailable.",
            ),
        }
    if str(agent.get("status") or "active").strip().lower() == "archived":
        return {
            "agentMissing": True,
            "agentStatusCode": "archived_agent",
            "agentStatusMessage": text_for(
                get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已归档，不能继续作为可用成员运行。",
                en="Missing valid Agent: this session references an archived Agent and cannot run it as an active member.",
            ),
        }
    return {
        "agentMissing": False,
        "agentStatusCode": "",
        "agentStatusMessage": "",
    }


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


def _session_agent_visible_in_indexes(summary: dict[str, Any]) -> bool:
    if bool(summary.get("hiddenFromIndex") or summary.get("hidden_from_index")):
        return False
    if str(summary.get("sessionKind") or "").strip().lower() == "supervised":
        return False
    if str(summary.get("agentStatusCode") or "").strip() == "deleted_agent":
        return True
    if bool(summary.get("agentMissing")):
        return False
    if not bool(str(summary.get("agentId") or "").strip()):
        return True
    return not bool(summary.get("agentMissing"))


@contextmanager
def _session_tool_workspace_override(session_workspace: str | Path, memory_workspace: str | Path | None = None):
    try:
        from core.infrastructure.mental_model import active_mental_workspace
        from core.orchestration.task_planner import task_storage_override
        from tools.shell_tools import workspace_root_override
        from tools.memory_tools import memory_storage_override
    except Exception:
        yield
        return
    memory_root = memory_workspace or session_workspace
    with (
        active_mental_workspace(session_workspace),
        workspace_root_override(session_workspace),
        memory_storage_override(memory_root),
        task_storage_override(session_workspace),
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


@dataclass
class SessionLiveOutputState:
    """Ephemeral live assistant output for one active web chat turn."""

    session_id: str
    turn_id: str = ""
    stage: str = ""
    thought: str = ""
    content: str = ""
    thought_delta: str = ""
    content_delta: str = ""
    replace_thought: bool = False
    replace_content: bool = False
    mental_snapshot: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback_events: list[dict[str, Any]] = field(default_factory=list)
    context_composition: dict[str, Any] | None = None
    updated_at: str = ""


def _live_output_delta(previous: str, current: str) -> tuple[str, bool]:
    previous_text = str(previous or "")
    current_text = str(current or "")
    if current_text.startswith(previous_text):
        return current_text[len(previous_text):], False
    return current_text, True


@dataclass
class SessionTurnCapture:
    """Collect live UI breadcrumbs so the web session can replay them."""

    session_id: str
    turn_id: str = ""
    thought: str = ""
    content: str = ""
    mental_state: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback_events: list[dict[str, Any]] = field(default_factory=list)
    _next_feedback_sequence: int = 1
    _latest_thought_sequence: int = 0
    _latest_thought_text: str = ""

    def note_thought(self, text: str) -> None:
        cleaned = _sanitize_thought_text(text)
        if cleaned:
            previous_total = self.thought
            previous_segment = self._latest_thought_text if self._latest_thought_sequence else ""
            if previous_total and not previous_segment and cleaned == previous_total:
                return
            next_total, next_text = self._resolve_thought_text_update(cleaned, previous_total, previous_segment)
            if not next_text:
                return
            if previous_segment and next_text == previous_segment:
                self.thought = next_total
                return
            self.thought = next_total
            self._latest_thought_text = next_text
            if self._latest_thought_sequence:
                self._update_latest_thought_event(next_text)
            else:
                self._latest_thought_sequence = self._append_feedback_event(
                    {
                        "kind": "thought",
                        "status": "running",
                        "summary": trim_lines(next_text, max_lines=2),
                        "resultPreview": next_text,
                    }
                )

    def _resolve_thought_text_update(self, cleaned: str, previous_total: str, previous_segment: str) -> tuple[str, str]:
        if not previous_total:
            return cleaned, cleaned
        if cleaned.startswith(previous_total):
            suffix = cleaned[len(previous_total):]
            if previous_segment:
                return cleaned, (f"{previous_segment}{suffix}" if suffix else previous_segment).strip()
            return cleaned, suffix.strip()
        if previous_segment and cleaned.startswith(previous_segment):
            if previous_total.endswith(previous_segment):
                next_total = f"{previous_total[:-len(previous_segment)]}{cleaned}"
            else:
                next_total = f"{previous_total}{cleaned}"
            return next_total, cleaned
        next_total = f"{previous_total}{cleaned}"
        next_segment = f"{previous_segment}{cleaned}" if previous_segment else cleaned
        return next_total, next_segment

    def _update_latest_thought_event(self, text: str) -> None:
        for index in range(len(self.feedback_events) - 1, -1, -1):
            latest = self.feedback_events[index]
            if (
                latest.get("kind") == "thought"
                and _coerce_nonnegative_int(latest.get("sequence")) == self._latest_thought_sequence
            ):
                updated = dict(latest)
                updated["status"] = "running"
                updated["summary"] = trim_lines(text, max_lines=2)
                updated["resultPreview"] = text
                updated["timestamp"] = _now_timestamp()
                self.feedback_events[index] = updated
                return

    def clear_thought(self) -> None:
        self.thought = ""

    def note_content(self, text: str) -> None:
        cleaned = _sanitize_message_content("assistant", text)
        if cleaned:
            self.content = cleaned

    def clear_content(self) -> None:
        self.content = ""

    def note_mental_state(self, *, mood: str = "", feeling: str = "", whisper: str = "") -> None:
        self.mental_state = {
            "mood": str(mood or "").strip(),
            "feeling": str(feeling or "").strip(),
            "whisper": str(whisper or "").strip(),
        }
        summary = trim_lines(
            self.mental_state.get("feeling") or self.mental_state.get("whisper") or self.mental_state.get("mood") or "",
            max_lines=2,
        )
        if summary:
            self._append_feedback_event(
                {
                    "kind": "mental",
                    "status": "running",
                    "summary": summary,
                }
            )

    def note_status_event(self, stage: str, summary: str, *, status: str = "running", name: str = "") -> None:
        stage_key = str(stage or "").strip().lower()
        cleaned_summary = trim_lines(summary or "", max_lines=3)
        if not stage_key and not cleaned_summary:
            return
        for existing in self.feedback_events:
            if existing.get("kind") == "status" and existing.get("name") == (name or stage_key):
                existing["status"] = _normalize_tool_call_status(status, default="running")
                if cleaned_summary:
                    existing["summary"] = cleaned_summary
                    existing["resultPreview"] = cleaned_summary
                existing["timestamp"] = _now_timestamp()
                return
        self._append_feedback_event(
            {
                "kind": "status",
                "status": _normalize_tool_call_status(status, default="running"),
                "name": name or stage_key,
                "summary": cleaned_summary or stage_key,
                "resultPreview": cleaned_summary or stage_key,
            }
        )

    def note_tool_event(
        self,
        name: str,
        status: str,
        summary: str = "",
        *,
        arguments: dict[str, Any] | None = None,
        result: Any = "",
        error: Any = "",
        duration_ms: Any = None,
        timeout_seconds: Any = None,
    ) -> None:
        tool_name = str(name or "").strip()
        if not tool_name:
            return
        entry = {
            "name": tool_name,
            "status": _normalize_tool_call_status(status, default="running"),
        }
        cleaned_summary = trim_lines(summary or "", max_lines=2)
        if cleaned_summary:
            entry["summary"] = cleaned_summary
        safe_arguments = _safe_tool_argument_details(arguments or {})
        if safe_arguments:
            entry["arguments"] = safe_arguments
        result_preview = _trim_tool_detail_text(result, max_chars=1200, max_lines=10)
        if result_preview:
            entry["resultPreview"] = result_preview
            entry["resultType"] = type(result).__name__
            entry["resultLength"] = len(str(result or ""))
        error_preview = _trim_tool_detail_text(error, max_chars=1200, max_lines=10)
        if error_preview:
            entry["error"] = error_preview
        numeric_duration = _coerce_tool_number(duration_ms)
        if numeric_duration is not None:
            entry["durationMs"] = numeric_duration
        numeric_timeout = _coerce_tool_number(timeout_seconds)
        if numeric_timeout is not None:
            entry["timeoutSeconds"] = numeric_timeout
        related_thought_sequence = self._latest_thought_sequence or 0
        for index in range(len(self.tool_calls) - 1, -1, -1):
            existing = self.tool_calls[index]
            if existing.get("name") == tool_name and existing.get("status") == "running":
                self.tool_calls[index] = entry
                self._update_running_tool_feedback_event(entry, related_thought_sequence=related_thought_sequence)
                self._latest_thought_sequence = 0
                self._latest_thought_text = ""
                return
        self.tool_calls.append(entry)
        if len(self.tool_calls) > 30:
            self.tool_calls = self.tool_calls[-30:]
        self._append_tool_feedback_event(entry, related_thought_sequence=related_thought_sequence)
        self._latest_thought_sequence = 0
        self._latest_thought_text = ""

    def _append_feedback_event(self, event: dict[str, Any]) -> int:
        sequence = self._next_feedback_sequence
        self._next_feedback_sequence += 1
        entry = {
            "sequence": sequence,
            "timestamp": _now_timestamp(),
            **event,
        }
        self.feedback_events.append(entry)
        if len(self.feedback_events) > 120:
            self.feedback_events = self.feedback_events[-120:]
        return sequence

    def _append_tool_feedback_event(self, tool_call: dict[str, Any], *, related_thought_sequence: int = 0) -> None:
        entry = {
            "kind": "tool",
            "status": _normalize_tool_call_status(tool_call.get("status"), default="running"),
            "name": str(tool_call.get("name") or "").strip(),
            "summary": trim_lines(tool_call.get("summary") or "", max_lines=2),
        }
        for key in (
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "tracePath",
        ):
            if key in tool_call:
                entry[key] = tool_call[key]
        if related_thought_sequence > 0:
            entry["relatedThoughtSequence"] = related_thought_sequence
        self._append_feedback_event(entry)

    def _update_running_tool_feedback_event(self, tool_call: dict[str, Any], *, related_thought_sequence: int = 0) -> None:
        tool_name = str(tool_call.get("name") or "").strip()
        if not tool_name:
            return
        for index in range(len(self.feedback_events) - 1, -1, -1):
            existing = self.feedback_events[index]
            if (
                existing.get("kind") == "tool"
                and existing.get("name") == tool_name
                and existing.get("status") == "running"
            ):
                sequence = existing.get("sequence")
                timestamp = existing.get("timestamp")
                updated = {
                    "sequence": sequence,
                    "timestamp": timestamp,
                    "kind": "tool",
                    "status": _normalize_tool_call_status(tool_call.get("status"), default="done"),
                    "name": tool_name,
                    "summary": trim_lines(tool_call.get("summary") or "", max_lines=2),
                }
                for key in (
                    "arguments",
                    "resultPreview",
                    "resultType",
                    "resultLength",
                    "error",
                    "durationMs",
                    "durationSeconds",
                    "timeoutSeconds",
                    "tracePath",
                ):
                    if key in tool_call:
                        updated[key] = tool_call[key]
                related = _coerce_nonnegative_int(existing.get("relatedThoughtSequence") or related_thought_sequence)
                if related > 0:
                    updated["relatedThoughtSequence"] = related
                self.feedback_events[index] = updated
                return
        self._append_tool_feedback_event(tool_call, related_thought_sequence=related_thought_sequence)


def list_sessions() -> list[dict]:
    """Return summarized sessions sourced from persisted chat state."""

    started_at = _perf_counter()
    _sync_agent_directory_project_root()
    signature = _session_list_source_signature()
    if _repair_agent_direct_session_collisions(source_signature=signature):
        signature = _session_list_source_signature()
    cached, should_build, waited_for_inflight = _begin_session_list_cache_build(
        now=started_at,
        signature=signature,
        allow_stale_matching_signature=True,
    )
    if cached is not None:
        sessions, cache_age_ms, conversation_count, agent_count = cached
        _record_session_list_loaded_event(
            session_count=len(sessions),
            conversation_count=conversation_count,
            agent_count=agent_count,
            elapsed_ms=_elapsed_ms(started_at),
            cache_hit=True,
            cache_age_ms=cache_age_ms,
            cache_ttl_ms=int(round(_SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
            waited_for_inflight=waited_for_inflight,
        )
        return sessions
    if not should_build:
        return []

    try:
        agent_by_id = _agent_lookup_for_conversations()
        active_id, conversations = _load_conversations(repair=False, agent_by_id=agent_by_id, lightweight=True)
        conversations = _append_agent_directory_conversations(conversations, agent_by_id=agent_by_id)
        sessions = []
        hidden_summaries = []
        for item in conversations:
            summary = _build_session_summary(item, hydrate_agent=False)
            if _session_agent_visible_in_indexes(summary):
                sessions.append(summary)
            else:
                hidden_summaries.append(summary)
        _record_session_agent_missing_index_batch_event(hidden_summaries, source="list_sessions")
        sessions.sort(
            key=lambda item: (
                0 if item["id"] == active_id else 1,
                -_timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
            )
        )
        _finish_session_list_cache_build(
            signature=signature,
            sessions=sessions,
            started_at=started_at,
            conversation_count=len(conversations),
            agent_count=len(agent_by_id),
        )
        _record_session_list_loaded_event(
            session_count=len(sessions),
            conversation_count=len(conversations),
            agent_count=len(agent_by_id),
            elapsed_ms=_elapsed_ms(started_at),
            cache_hit=False,
            cache_age_ms=0,
            cache_ttl_ms=int(round(_SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
            waited_for_inflight=waited_for_inflight,
        )
        return sessions
    except Exception:
        _finish_session_list_cache_build(signature=signature)
        raise


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


def get_session_detail(session_id: str) -> dict | None:
    """Return a session detail payload by persisted conversation id."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None

    with _RUNNING_SESSIONS_LOCK:
        active_turn_id = str(_SESSION_ACTIVE_TURN_IDS.get(normalized_session_id) or "").strip()
        session_running = normalized_session_id in _RUNNING_SESSION_IDS
    _reconcile_stale_session_ledger(
        normalized_session_id,
        active_turn_id=active_turn_id if session_running else "",
        reason="detail_loaded_after_restart",
    )
    _ensure_agent_directory_conversation_materialized(normalized_session_id, source="get_session_detail")
    agent_by_id = _agent_lookup_for_conversations()
    payload = load_chat_state(PROJECT_ROOT)
    target = _load_conversation_detail_target(
        normalized_session_id,
        payload=payload,
        repair=True,
        agent_by_id=agent_by_id,
    )
    if target is not None:
        return _build_session_detail(target)
    fallback = _agent_directory_session_stub_for_id(normalized_session_id, agent_by_id=agent_by_id)
    if fallback is not None:
        return _build_session_detail(fallback)
    return None


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
        messages = normalize_chat_messages(conversation.get("messages") or [])

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


def append_cli_agent_lifecycle_event(
    session_id: str,
    *,
    event: str = "closed",
    terminal_session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append a folded CLI Agent lifecycle event to the persisted conversation."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    terminal = dict(terminal_session or {}) if isinstance(terminal_session, dict) else {}
    normalized_event = str(event or "closed").strip().lower() or "closed"
    cli_run_id = str(terminal.get("cliRunId") or "").strip()
    terminal_session_id = str(terminal.get("terminalSessionId") or "").strip()
    lifecycle_subject = cli_run_id or terminal_session_id
    if not lifecycle_subject:
        return None
    lifecycle_key = f"cli_agent_lifecycle:{normalized_event}:{lifecycle_subject}"
    label = str(terminal.get("label") or terminal.get("adapterId") or terminal.get("agentType") or "CLI Agent").strip()
    lang = get_web_language()
    timestamp = _now_timestamp()
    if normalized_event in {"linked", "session_linked"}:
        content = text_for(
            lang,
            zh=f"{label} 已连接 CLI 会话。",
            en=f"{label} linked to a CLI session.",
        )
    elif normalized_event == "resumed":
        content = text_for(
            lang,
            zh=f"{label} 已恢复 CLI 会话。",
            en=f"{label} resumed the CLI session.",
        )
    else:
        content = text_for(
            lang,
            zh=f"{label} 已关闭。",
            en=f"{label} closed.",
        )
    metadata = {
        "kind": "cli_agent_lifecycle",
        "event": normalized_event,
        "status": normalized_event,
        "lifecycleKey": lifecycle_key,
        "cliRunId": cli_run_id,
        "terminalSessionId": terminal_session_id,
        "adapterId": str(terminal.get("adapterId") or terminal.get("agentType") or "").strip(),
        "label": label,
        "sourceSessionId": normalized_session_id,
        "sourceMessageId": str(terminal.get("sourceMessageId") or "").strip(),
        "sourceRunId": str(terminal.get("sourceRunId") or "").strip(),
        "linkedSourceRunIds": list(terminal.get("linkedSourceRunIds") or []),
        "cwd": str(terminal.get("cwd") or "").strip(),
        "mode": str(terminal.get("mode") or "readonly").strip() or "readonly",
        "lockKey": str(terminal.get("lockKey") or "").strip(),
        "cliSessionId": str(terminal.get("cliSessionId") or "").strip(),
        "cliSessionIdSource": str(terminal.get("cliSessionIdSource") or "").strip(),
        "eventAt": timestamp,
        "closedAt": timestamp if normalized_event == "closed" else "",
        "linkedAt": timestamp if normalized_event in {"linked", "session_linked"} else "",
        "resumedAt": timestamp if normalized_event == "resumed" else "",
        "folded": True,
    }
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return None
        messages = normalize_chat_messages(conversation.get("messages") or [])
        existing = _find_cli_agent_lifecycle_message(
            normalized_session_id,
            messages,
            lifecycle_key=lifecycle_key,
        )
        if existing is not None:
            _append_cli_agent_lifecycle_sidecar(normalized_session_id, existing)
            return existing
        existing_sidecar = _find_cli_agent_lifecycle_sidecar_message(
            normalized_session_id,
            lifecycle_key=lifecycle_key,
        )
        event_entry = _make_chat_message("assistant", content, metadata=metadata)
        if existing_sidecar is not None:
            event_entry["timestamp"] = str(existing_sidecar.get("timestamp") or event_entry["timestamp"])
        conversation["messages"] = messages + [event_entry]
        conversation["updated_at"] = event_entry["timestamp"]
        payload["updated_at"] = event_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _append_cli_agent_lifecycle_sidecar(normalized_session_id, event_entry)
        normalized_messages = _normalize_messages(normalized_session_id, conversation["messages"])
        normalized_event_entry = _find_cli_agent_lifecycle_message(
            normalized_session_id,
            normalized_messages,
            lifecycle_key=lifecycle_key,
        )
    _append_session_conversation_event(
        normalized_session_id,
        str(terminal.get("sourceTurnId") or terminal.get("turnId") or f"cli-lifecycle:{lifecycle_subject}"),
        EVENT_CLI_SESSION_LIFECYCLE,
        status=normalized_event,
        payload={"lifecycle": metadata},
        source="cli_agent_lifecycle",
        visible_in_model=normalized_event in {"closed", "failed", "timeout"},
        projection_kind="cli_agent_lifecycle",
        correlation_id=lifecycle_key,
        source_kind="cli_agent",
    )
    _record_session_cycle_message(
        normalized_session_id,
        event_entry,
        event="cli_agent_lifecycle",
        status=normalized_event,
    )
    _record_cli_agent_lifecycle_event(
        normalized_session_id,
        event=normalized_event,
        metadata=metadata,
    )
    _publish_session_detail_snapshot(normalized_session_id)
    return normalized_event_entry


def append_cli_agent_task_result_event(
    session_id: str,
    *,
    task_result: dict[str, Any],
    wake_agent: bool = False,
    wake_reason: str = "",
) -> dict[str, Any] | None:
    """Persist a CLI Agent task result and optionally wake the owning Agent."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or not isinstance(task_result, dict):
        return None
    task_id = str(task_result.get("taskId") or "").strip()
    terminal_session_id = str(task_result.get("terminalSessionId") or "").strip()
    status = str(task_result.get("status") or "").strip().lower() or "unknown"
    result_subject = task_id or terminal_session_id
    if not result_subject:
        return None
    result_key = f"cli_agent_task_result:{result_subject}:{status}"
    content = _format_cli_agent_task_result_content(task_result)
    metadata = {
        "kind": "cli_agent_task_result",
        "resultKey": result_key,
        "taskId": task_id,
        "status": status,
        "code": str(task_result.get("code") or "").strip(),
        "adapterId": str(task_result.get("adapterId") or task_result.get("agentType") or "").strip(),
        "label": str(task_result.get("label") or "CLI Agent").strip(),
        "sourceSessionId": normalized_session_id,
        "terminalSessionId": terminal_session_id,
        "cliRunId": str(task_result.get("cliRunId") or "").strip(),
        "lockKey": str(task_result.get("lockKey") or "").strip(),
        "cliSessionId": str(task_result.get("cliSessionId") or "").strip(),
        "cwd": str(task_result.get("cwd") or "").strip(),
        "taskHash": str(task_result.get("taskHash") or "").strip(),
        "taskPreview": str(task_result.get("taskPreview") or "").strip(),
        "completionReason": str(task_result.get("completionReason") or "").strip(),
        "completedAt": str(task_result.get("completedAt") or _now_timestamp()).strip(),
        "timedOut": bool(task_result.get("timedOut")),
        "folded": True,
    }
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return None
        messages = normalize_chat_messages(conversation.get("messages") or [])
        existing = _find_cli_agent_task_result_message(messages, result_key=result_key)
        if existing is not None:
            return existing
        else:
            result_entry = _make_chat_message("assistant", content, metadata=metadata)
            conversation["messages"] = messages + [result_entry]
            conversation["updated_at"] = result_entry["timestamp"]
            payload["updated_at"] = result_entry["timestamp"]
            save_chat_state(PROJECT_ROOT, payload)
    journal_turn_id = str(
        task_result.get("sourceTurnId")
        or task_result.get("turnId")
        or _current_session_turn_id(normalized_session_id)
        or f"cli-task:{result_subject}"
    ).strip()
    journal_tool_call = {
        "name": "cli_agent_run_tool",
        **task_result,
        "status": status,
        "result": content,
        "resultPreview": trim_lines(content, max_lines=8),
    }
    _append_session_conversation_event(
        normalized_session_id,
        journal_turn_id,
        EVENT_CLI_TASK_RESULT,
        status=status,
        payload={"toolCall": journal_tool_call},
        source="cli_agent_task_kernel",
        visible_in_model=True,
        projection_kind="cli_agent_task_result",
        tool_call_id=task_id,
        correlation_id=result_key,
        source_kind="cli_agent",
    )
    _record_session_cycle_message(
        normalized_session_id,
        result_entry,
        event="cli_agent_task_result",
        status=status,
    )
    signal = _record_chat_next_state_signal(
        session_id=normalized_session_id,
        turn_id=_current_session_turn_id(normalized_session_id),
        source="runtime",
        kind="cli_agent_result",
        polarity="negative" if status in {"failed", "timeout", "error"} else "neutral",
        mode="directive",
        related_event_code="conversation.cli_agent.task_result",
        summary=trim_lines(content, max_lines=8),
        metadata={
            "taskId": task_id,
            "terminalSessionId": terminal_session_id,
            "status": status,
            "wakeReason": str(wake_reason or "").strip(),
        },
    )
    wake_status = ""
    if wake_agent:
        wake_status = _wake_agent_for_cli_agent_task_result(
            normalized_session_id,
            task_result=task_result,
            result_content=content,
            signal_id=str((signal or {}).get("signalId") or ""),
            wake_reason=wake_reason,
        )
    _record_cli_agent_task_result_event(
        normalized_session_id,
        task_result=task_result,
        wake_status=wake_status,
        signal_id=str((signal or {}).get("signalId") or ""),
    )
    _publish_session_detail_snapshot(normalized_session_id)
    if isinstance(result_entry, dict):
        result_entry = dict(result_entry)
        if wake_status:
            result_entry["_cliAgentWakeStatus"] = wake_status
    return result_entry


def _format_cli_agent_task_result_content(task_result: dict[str, Any]) -> str:
    label = str(task_result.get("label") or task_result.get("adapterId") or task_result.get("agentType") or "CLI Agent").strip()
    status = str(task_result.get("status") or "unknown").strip().lower()
    status_label = {
        "completed": "完成",
        "failed": "失败",
        "timeout": "超时",
        "sent": "已发送",
        "running": "运行中",
        "error": "错误",
    }.get(status, status or "未知")
    lines = [
        f"CLI Agent 任务结果回流：{label}",
        f"状态：{status_label}",
    ]
    code = str(task_result.get("code") or "").strip()
    if code:
        lines.append(f"代码：{code}")
    cwd = str(task_result.get("cwd") or "").strip()
    if cwd:
        lines.append(f"目录：{cwd}")
    reason = str(task_result.get("completionReason") or "").strip()
    if reason:
        lines.append(f"原因：{reason}")
    preview = trim_lines(task_result.get("taskPreview") or "", max_lines=2)
    if preview:
        lines.append(f"任务：{preview}")
    segments = list(task_result.get("resultSegments") or [])
    segment_lines: list[str] = []
    for item in segments[-8:]:
        if not isinstance(item, dict):
            continue
        text = trim_lines(item.get("text") or "", max_lines=8)
        if not text:
            continue
        kind = str(item.get("kind") or "output").strip() or "output"
        segment_lines.append(f"- [{kind}] {text}")
    if segment_lines:
        lines.append("最近完整片段：")
        lines.extend(segment_lines)
    else:
        stdout = trim_lines(task_result.get("stdoutPreview") or "", max_lines=12)
        if stdout:
            lines.append("输出摘要：")
            lines.append(stdout)
    if status in {"failed", "timeout", "error"}:
        lines.append("请基于该失败/超时结果判断下一步策略，不要重复调用同一个 CLI 任务，除非你需要验证新的假设。")
    return "\n".join(line for line in lines if str(line or "").strip()).strip()


def _current_session_turn_id(session_id: str) -> str:
    with _RUNNING_SESSIONS_LOCK:
        return str(_SESSION_ACTIVE_TURN_IDS.get(session_id) or "").strip()


def _wake_agent_for_cli_agent_task_result(
    session_id: str,
    *,
    task_result: dict[str, Any],
    result_content: str,
    signal_id: str = "",
    wake_reason: str = "",
) -> str:
    if _is_session_running(session_id):
        return "guided_running"
    lang = get_web_language()
    prompt = "\n".join(
        [
            "CLI Agent 已返回任务结果，请把它当作当前会话的工具结果继续处理。",
            "先吸收结果，再决定是否需要继续主 Agent 侧动作；不要因为看到 CLI 结果而重复启动同一个 CLI Agent。",
            result_content,
        ]
    ).strip()
    requested_leases = ["readonly_chat"]
    lease_decision = _check_chat_turn_lease_decision(requested_leases)
    if not lease_decision.allowed:
        return "wake_blocked_by_lease"
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return "wake_session_missing"
        if _is_session_running(session_id):
            return "guided_running"
        _ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        _resolve_active_agent_for_turn(session_id, agent_id, lang=lang)
        history_messages = normalize_chat_messages(conversation.get("messages") or [])
        active_task = _normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not _is_task_tool_backed_active_task(active_task):
            active_task = None
        turn_control = _create_session_turn_control(session_id)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = _now_timestamp()
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = conversation["updated_at"]
        save_chat_state(PROJECT_ROOT, payload)
        _set_session_running(session_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=prompt,
            started_at=conversation["updated_at"],
            updated_at=conversation["updated_at"],
        )
    _set_session_waiting_live_output(session_id, turn_id=turn_control.turn_id)
    _record_session_turn_started_event(
        session_id,
        turn_id=turn_control.turn_id,
        leases=requested_leases,
        user_message=prompt,
        raw_user_message="",
        user_message_source="cli_agent_result",
    )
    context = {
        "session_id": session_id,
        "turn_id": turn_control.turn_id,
        "turn_control": turn_control,
        "user_message": prompt,
        "raw_user_message": "",
        "user_message_source": "cli_agent_result",
        "history_messages": history_messages,
        "mental_model_enabled": None,
        "active_task": active_task,
        "agent_id": agent_id,
        "leases": requested_leases,
        "llm_slot": SESSION_LLM_SLOT_DIALOGUE,
        "submit_timing_fields": {"source": "cli_agent_result", "signalId": signal_id, "wakeReason": str(wake_reason or "").strip()},
        "submit_started_at_monotonic": _perf_counter(),
    }
    _record_session_turn_scheduled_event(context)
    try:
        _schedule_session_turn(context)
    except Exception as exc:
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=prompt,
            summary=f"{type(exc).__name__}: {exc}",
        )
        _set_session_running(session_id, False, turn_id=turn_control.turn_id)
        _clear_session_turn_control(session_id, turn_id=turn_control.turn_id)
        _persist_session_turn_failure(session_id, context, exc)
        return "wake_schedule_failed"
    return "wake_scheduled"


def get_active_session_detail() -> dict | None:
    """Return the current active conversation detail when available."""

    active_id, conversations = _load_conversations()
    if not conversations:
        return None
    target_id = active_id or conversations[0]["id"]
    for item in conversations:
        if item["id"] == target_id:
            return _build_session_detail(item)
    return _build_session_detail(conversations[0])


def get_active_session_summary() -> dict | None:
    """Return the current active conversation summary for shell-level polling."""

    agent_by_id = _agent_lookup_for_conversations()
    active_id, conversations = _load_conversations(repair=False, agent_by_id=agent_by_id, lightweight=True)
    conversations = _append_agent_directory_conversations(conversations, agent_by_id=agent_by_id)
    if not conversations:
        return None
    target_id = str(active_id or "").strip()
    target = next(
        (
            item
            for item in conversations
            if isinstance(item, dict) and str(item.get("id") or "").strip() == target_id
        ),
        None,
    )
    if target is None:
        target = next((item for item in conversations if isinstance(item, dict)), None)
    if target is None:
        return None
    target = _with_direct_session_agent_for_summary(target, agent_by_id=agent_by_id)
    return _build_session_summary(target, hydrate_agent=False)


def _with_direct_session_agent_for_summary(
    conversation: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach a direct-session Agent to a lightweight summary copy without repairing state."""

    session_id = str(conversation.get("id") or conversation.get("conversation_id") or "").strip()
    if not session_id:
        return conversation
    existing_agent_id = str(conversation.get("agentId") or conversation.get("agent_id") or "").strip()
    existing_agent = _agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
    if existing_agent is not None:
        updated = dict(conversation)
        updated["_agent"] = dict(existing_agent)
        updated["_agentLookupChecked"] = True
        return updated
    if existing_agent_id:
        return conversation
    for agent in agent_by_id.values():
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or str(agent.get("directSessionId") or "").strip() != session_id:
            continue
        updated = dict(conversation)
        updated["agent_id"] = agent_id
        updated["agentId"] = agent_id
        updated["_agent"] = dict(agent)
        updated["_agentLookupChecked"] = True
        updated["agentMissingId"] = ""
        updated["agentMissing"] = False
        updated["agentStatusCode"] = ""
        updated["agentDirectSessionMismatch"] = False
        updated["agentPrimaryDirectSessionId"] = ""
        return updated
    return conversation


def create_chat_session(
    *,
    title: str = "",
    llm_bindings: dict[str, Any] | None = None,
    created_by: str = "user",
) -> dict:
    """Create a new empty chat session and make it active."""

    lang = get_web_language()
    normalized_llm_bindings = _normalize_session_agent_llm_bindings(llm_bindings)
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
        )
        _ensure_conversation_workspace_metadata(conversation)
        _sync_agent_directory_project_root()
        agent = ensure_agent_for_session(
            session_id,
            display_name=normalized_title,
            llm_bindings=normalized_llm_bindings,
            session_workspace_path=str(conversation.get("workspace_path") or _session_workspace_relative_path(session_id)),
            created_by=created_by,
        )
        agent_id = str(agent.get("agentId") or "").strip()
        if agent_id:
            conversation["agent_id"] = agent_id
            conversation["agentId"] = agent_id
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    return get_session_detail(session_id) or {}


def create_supervised_agent_session(
    *,
    agent_id: str,
    title: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a hidden supervised-evolution session bound to an existing Agent."""

    lang = get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise SessionValidationError(
            text_for(lang, zh="监督会话缺少 Agent 绑定。", en="Supervised session is missing an Agent binding.")
        )
    agent = get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise SessionValidationError(_session_agent_unavailable_message("missing_agent", lang=lang))
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
            or text_for(lang, zh="监督进化隐藏会话", en="Hidden supervised evolution session")
        )
        conversation = _make_empty_conversation(session_id, title=display_title, timestamp=now)
        conversation.update(
            {
                "agent_id": normalized_agent_id,
                "agentId": normalized_agent_id,
                "session_kind": "supervised",
                "sessionKind": "supervised",
                "hidden_from_index": True,
                "hiddenFromIndex": True,
                "task_title": display_title,
                "taskTitle": display_title,
                "supervised_context": dict(metadata or {}) if isinstance(metadata, dict) else {},
            }
        )
        _ensure_conversation_workspace_metadata(conversation)
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["updated_at"] = now
        payload["conversations"] = conversations
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    return get_session_detail(session_id) or {}


def list_child_sessions(session_id: str) -> list[dict[str, Any]]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return []
    _, conversations = _load_conversations()
    root_id = _root_session_id_for_conversations(normalized_session_id, conversations)
    children = [
        _build_session_summary(item)
        for item in conversations
        if str(item.get("parentSessionId") or "").strip() == root_id
        and str(item.get("sessionKind") or "").strip() == "child"
    ]
    children.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return children


def create_child_session(
    parent_session_id: str,
    *,
    user_request: str,
    task_title: str = "",
    split_reason: str = "",
    inherited_facts: list[str] | None = None,
    relevant_files: list[str] | None = None,
    relevant_logs: list[str] | None = None,
    constraints: list[str] | None = None,
    excluded_context_summary: str = "",
    auto_start: bool = True,
    switch_to_child: bool = True,
    source: str = "agent_auto_split",
) -> dict[str, Any]:
    lang = get_web_language()
    parent_id = str(parent_session_id or "").strip()
    request_text = str(user_request or "").strip()
    if not parent_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到父会话。", en="Parent session not found."))
    if not request_text:
        raise SessionValidationError(text_for(lang, zh="请输入子对话要处理的事项。", en="Enter the child session task."))
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        _materialize_agent_directory_conversation_locked(payload, parent_id, source="create_child_session")
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        source_parent = _find_conversation_entry(payload, parent_id)
        if source_parent is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到父会话。", en="Parent session not found."))
        _ensure_conversation_workspace_metadata(source_parent)
        _ensure_conversation_agent_metadata(source_parent)
        normalized_parent = _normalize_conversation(source_parent, ensure_workspace=False)
        root_id = str((normalized_parent or {}).get("rootSessionId") or parent_id).strip() or parent_id
        if str((normalized_parent or {}).get("sessionKind") or "main") == "child":
            root_id = str((normalized_parent or {}).get("rootSessionId") or (normalized_parent or {}).get("parentSessionId") or parent_id).strip() or parent_id
        parent = _find_conversation_entry(payload, root_id) or source_parent
        _ensure_conversation_workspace_metadata(parent)
        _ensure_conversation_agent_metadata(parent)
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = _now_timestamp()
        child_id = _new_conversation_id(existing_ids)
        title = trim_lines(task_title or request_text, max_lines=1).strip() or text_for(lang, zh="子对话", en="Child session")
        agent_id = str(parent.get("agent_id") or parent.get("agentId") or "").strip()
        handoff_context = {
            "source": str(source or "agent_auto_split").strip() or "agent_auto_split",
            "parentSessionId": root_id,
            "sourceSessionId": parent_id,
            "parentMessageId": _latest_user_message_id(parent_id, source_parent.get("messages") or []),
            "triggeringUserMessage": request_text,
            "splitReason": split_reason or "Agent judged this request as a separate task.",
            "inheritedFacts": list(inherited_facts or []),
            "relevantFiles": list(relevant_files or []),
            "relevantLogs": list(relevant_logs or []),
            "constraints": list(constraints or []),
            "excludedContextSummary": excluded_context_summary,
        }
        child = _make_empty_conversation(child_id, title=title, timestamp=now)
        child.update(
            {
                "agent_id": agent_id,
                "agentId": agent_id,
                "session_kind": "child",
                "parent_session_id": root_id,
                "root_session_id": root_id,
                "task_title": title,
                "child_status": "queued" if auto_start else "idle",
                "handoff_context": _normalize_child_handoff_context(handoff_context),
            }
        )
        _ensure_conversation_workspace_metadata(child)
        child_ids = _normalize_string_list(parent.get("child_session_ids") or parent.get("childSessionIds"))
        if child_id not in child_ids:
            child_ids.append(child_id)
        parent["child_session_ids"] = child_ids
        parent["active_child_session_id"] = child_id
        parent_messages = normalize_chat_messages(parent.get("messages") or [])
        parent_messages.append(
            _make_chat_message(
                "assistant",
                _child_session_created_card(child_id=child_id, title=title, auto_start=auto_start),
                metadata={
                    "kind": "child_session_card",
                    "childSessionId": child_id,
                    "childStatus": "queued" if auto_start else "idle",
                    "taskTitle": title,
                },
            )
        )
        parent["messages"] = parent_messages
        parent["updated_at"] = now
        conversations.append(child)
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        if switch_to_child:
            payload["active_conversation_id"] = child_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    _record_child_session_event(
        "created",
        parent_session_id=root_id,
        child_session_id=child_id,
        fields={"autoStart": bool(auto_start), "switchToChild": bool(switch_to_child), "taskTitle": title},
    )
    if auto_start:
        _record_child_session_event("autostarted", parent_session_id=root_id, child_session_id=child_id)
        submit_session_message(
            child_id,
            _child_session_initial_prompt(request_text, handoff_context),
            message_metadata={"childSessionStart": True, "parentSessionId": root_id},
            message_source="child_session_autostart",
            lightweight_response=True,
        )
    return {
        "status": "created",
        "parentSessionId": root_id,
        "childSessionId": child_id,
        "childSession": get_session_detail(child_id) or {},
        "parentSession": get_session_detail(root_id) or {},
        "switched": bool(switch_to_child),
        "autoStarted": bool(auto_start),
    }


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


def _delete_chat_session_state(session_id: str, *, activate_replacement: bool = False) -> dict[str, str]:
    """Delete one chat session and return ids needed by UI and Agent rebind callers."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    next_active_id = ""
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        _materialize_agent_directory_conversation_locked(payload, conversation_id, source="delete_chat_session")
        payload = _repair_stale_running_conversations(payload)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []

        target_index = -1
        target_conversation: dict[str, Any] | None = None
        for index, item in enumerate(conversations):
            if not isinstance(item, dict):
                continue
            if str(item.get("conversation_id") or "").strip() == conversation_id:
                target_index = index
                target_conversation = item
                break
        if target_index < 0 or target_conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_conversation_workspace_metadata(target_conversation)
        _ensure_conversation_agent_metadata(target_conversation)
        target_agent_id = str(target_conversation.get("agent_id") or target_conversation.get("agentId") or "").strip()
        target_agent = get_agent(target_agent_id, include_archived=False) if target_agent_id else None
        target_agent_direct_session_id = str((target_agent or {}).get("directSessionId") or "").strip()

        normalized_target = _normalize_conversation(target_conversation) or {}
        target_phase = _conversation_phase(conversation_id, normalized_target)
        _record_session_delete_event(
            "requested",
            session_id=conversation_id,
            outcome="requested",
            fields={
                "phase": target_phase,
                "agentId": target_agent_id,
                "messageCount": len(normalize_chat_messages(target_conversation.get("messages") or [])),
            },
        )
        if target_phase in {"running", "stopping"}:
            _record_session_delete_event(
                "blocked",
                session_id=conversation_id,
                outcome="busy",
                level="warning",
                fields={
                    "reason": "busy",
                    "phase": target_phase,
                    "agentId": target_agent_id,
                },
            )
            raise SessionBusyError(
                text_for(
                    lang,
                    zh="当前会话仍在运行或停止中，请先等待这一轮收束后再删除。",
                    en="This session is still running or stopping. Wait for the current turn to close before deleting it.",
                )
            )

        remaining = [
            item
            for index, item in enumerate(conversations)
            if index != target_index and isinstance(item, dict)
        ]
        normalized_remaining = [
            item
            for item in (_normalize_conversation(raw) for raw in remaining)
            if item is not None
        ]
        replacement_direct_session_id = ""
        if target_agent and target_agent_direct_session_id == conversation_id:
            update_agent_instance(
                target_agent_id,
                direct_session_id="",
                metadata={"previousDirectSessionId": conversation_id},
            )

        current_active_id = str(payload.get("active_conversation_id") or "").strip()
        if any(item["id"] == current_active_id for item in normalized_remaining) and current_active_id != conversation_id:
            next_active_id = current_active_id
        elif normalized_remaining:
            latest = max(
                normalized_remaining,
                key=lambda item: _timestamp_sort_key(item.get("updatedAt") or ""),
            )
            next_active_id = latest["id"]
        else:
            now = _now_timestamp()
            next_active_id = _new_conversation_id({conversation_id})
            replacement_conversation = _make_empty_conversation(
                next_active_id,
                title=text_for(lang, zh="新会话", en="New session"),
                timestamp=now,
            )
            remaining = [
                replacement_conversation
            ]

        now = _now_timestamp()
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["active_conversation_id"] = next_active_id
        payload["updated_at"] = now
        payload["conversations"] = remaining
        save_chat_state(PROJECT_ROOT, payload)

    _invalidate_session_list_cache()
    if target_agent and target_agent_direct_session_id == conversation_id:
        _record_session_delete_event(
            "agent_unbound",
            session_id=conversation_id,
            outcome="unbound",
            fields={
                "agentId": target_agent_id,
                "previousDirectSessionId": conversation_id,
            },
        )
    _record_session_delete_event(
        "deleted",
        session_id=conversation_id,
        outcome="deleted",
        fields={
            "nextActiveSessionId": next_active_id,
            "agentId": target_agent_id,
            "replacementDirectSessionId": replacement_direct_session_id,
            "remainingCount": len(remaining),
        },
    )
    _set_session_running(conversation_id, False)
    _clear_session_turn_control(conversation_id)
    _clear_session_live_output(conversation_id)
    return {
        "nextActiveSessionId": next_active_id,
        "replacementDirectSessionId": replacement_direct_session_id,
    }


def delete_chat_session(session_id: str) -> dict:
    """Delete one chat session and return the next active session detail."""

    delete_result = _delete_chat_session_state(session_id)
    next_active_id = str(delete_result.get("nextActiveSessionId") or "").strip()
    target = _load_conversation_detail_target(next_active_id, repair=False, agent_by_id={})
    return _build_lightweight_session_detail(target) if target is not None else {}


def delete_chat_session_lightweight(session_id: str, *, activate_replacement: bool = False) -> dict[str, Any]:
    """Delete one chat session and return a lightweight UI handoff payload."""

    deleted_session_id = str(session_id or "").strip()
    delete_result = _delete_chat_session_state(deleted_session_id, activate_replacement=activate_replacement)
    return {
        "deleted": True,
        "deletedSessionId": deleted_session_id,
        "nextActiveSessionId": str(delete_result.get("nextActiveSessionId") or "").strip(),
        "replacementDirectSessionId": str(delete_result.get("replacementDirectSessionId") or "").strip(),
    }


def reset_agent_direct_session_lightweight(
    session_id: str,
    *,
    agent_id: str,
    title: str = "",
) -> dict[str, Any]:
    """Create and bind a replacement direct session before deleting the old one."""

    lang = get_web_language()
    old_session_id = str(session_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not old_session_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
    if not normalized_agent_id:
        raise SessionValidationError(text_for(lang, zh="缺少 Agent ID。", en="Agent id is required."))

    replacement_session_id = ""
    created_at = _now_timestamp()
    normalized_title = trim_lines(title or "", max_lines=1).strip() or text_for(lang, zh="新会话", en="New session")
    try:
        with _CHAT_STATE_LOCK:
            payload = load_chat_state(PROJECT_ROOT)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            _materialize_agent_directory_conversation_locked(payload, old_session_id, source="agent_reset_direct_session")
            payload = _repair_stale_running_conversations(payload)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            old_conversation = _find_conversation_entry(payload, old_session_id)
            if old_conversation is None:
                raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
            normalized_old = _normalize_conversation(old_conversation) or {}
            old_phase = _conversation_phase(old_session_id, normalized_old)
            _record_session_delete_event(
                "agent_reset_replacement_requested",
                session_id=old_session_id,
                outcome="requested",
                fields={"agentId": normalized_agent_id, "phase": old_phase},
            )
            if old_phase in {"running", "stopping"}:
                raise SessionBusyError(
                    text_for(
                        lang,
                        zh="当前会话仍在运行或停止中，请先等待这一轮收束后再重置 Agent。",
                        en="This session is still running or stopping. Wait for the current turn to close before resetting the Agent.",
                    )
                )
            existing_ids = {
                str(item.get("conversation_id") or "").strip()
                for item in conversations
                if isinstance(item, dict)
            }
            replacement_session_id = _new_conversation_id(existing_ids | {old_session_id})
            replacement_conversation = _make_empty_conversation(
                replacement_session_id,
                title=normalized_title,
                timestamp=created_at,
            )
            _ensure_conversation_workspace_metadata(replacement_conversation)
            replacement_conversation["agent_id"] = normalized_agent_id
            replacement_conversation["agentId"] = normalized_agent_id
            conversations.append(replacement_conversation)
            payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
            payload["active_conversation_id"] = replacement_session_id
            payload["updated_at"] = created_at
            payload["conversations"] = conversations
            save_chat_state(PROJECT_ROOT, payload)
        _invalidate_session_list_cache()

        agent_directory_service.update_agent_instance(
            normalized_agent_id,
            direct_session_id=replacement_session_id,
            metadata={"previousDirectSessionId": old_session_id},
        )
        delete_result = _delete_chat_session_state(old_session_id, activate_replacement=True)
        _record_session_delete_event(
            "agent_reset_replacement_bound",
            session_id=old_session_id,
            outcome="bound",
            fields={
                "agentId": normalized_agent_id,
                "replacementDirectSessionId": replacement_session_id,
                "nextActiveSessionId": str(delete_result.get("nextActiveSessionId") or "").strip(),
            },
        )
        return {
            "deleted": True,
            "deletedSessionId": old_session_id,
            "nextActiveSessionId": str(delete_result.get("nextActiveSessionId") or replacement_session_id).strip(),
            "replacementDirectSessionId": replacement_session_id,
        }
    except Exception as exc:
        if replacement_session_id:
            _remove_replacement_direct_session_after_failed_agent_reset(
                replacement_session_id,
                agent_id=normalized_agent_id,
                fallback_active_session_id=old_session_id,
            )
        try:
            agent_directory_service.update_agent_instance(
                normalized_agent_id,
                direct_session_id=old_session_id,
                metadata={"previousDirectSessionId": replacement_session_id},
            )
        except Exception:
            pass
        _record_session_delete_event(
            "agent_reset_replacement_failed",
            session_id=old_session_id,
            outcome="failed",
            level="error",
            fields={
                "agentId": normalized_agent_id,
                "replacementDirectSessionId": replacement_session_id,
                "errorType": type(exc).__name__,
            },
        )
        raise


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

    messages = normalize_chat_messages(conversation.get("messages") or [])
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


def request_stop_session_turn(session_id: str) -> dict:
    """Interrupt one active web chat turn and persist the partial run surface."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    detail = get_session_detail(conversation_id)
    if detail is None:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    if not _is_session_running(conversation_id):
        return detail

    controller = _get_session_turn_control(conversation_id)
    if controller is None:
        controller = _restore_missing_session_turn_control(conversation_id)
        _set_session_running(conversation_id, True, turn_id=controller.turn_id)

    controller.request_stop(
        text_for(
            lang,
            zh="操作者请求停止当前轮。",
            en="The operator requested this turn to stop.",
        )
    )
    stop_snapshot = controller.snapshot()
    _cancel_queued_session_turn(conversation_id, str(stop_snapshot.get("turnId") or controller.turn_id))
    _record_chat_next_state_signal(
        session_id=conversation_id,
        turn_id=str(stop_snapshot.get("turnId") or controller.turn_id),
        source="user",
        kind="user_stops",
        polarity="negative",
        mode="directive",
        related_event_code="conversation.user_stop_requested",
        summary=text_for(
            lang,
            zh="用户请求停止当前对话轮次。",
            en="The user requested the current chat turn to stop.",
        ),
        metadata={
            "stopReason": stop_snapshot.get("stopReason") or "",
            "stopRequestedAt": stop_snapshot.get("stopRequestedAt") or "",
        },
    )
    _persist_session_interrupted_snapshot(
        conversation_id,
        stop_snapshot,
        lang=lang,
    )
    _set_session_running(conversation_id, False, turn_id=controller.turn_id)
    controller.mark_released_to_user()
    _publish_session_detail_snapshot(conversation_id)
    return get_session_detail(conversation_id) or detail


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


def submit_session_guidance(session_id: str, content: str, *, mode: str = "safe") -> dict:
    """Record operator guidance for a running turn, optionally interrupting it."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    detail = get_session_detail(conversation_id)
    if detail is None:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))

    guidance_text = str(content or "").strip()
    if not guidance_text:
        raise SessionValidationError(text_for(lang, zh="引导内容不能为空。", en="Guidance content cannot be empty."))

    normalized_mode = str(mode or "").strip().lower().replace("-", "_")
    if normalized_mode not in {"safe", "interrupt"}:
        raise SessionValidationError(text_for(lang, zh="引导模式无效。", en="Invalid guidance mode."))

    controller = _get_session_turn_control(conversation_id)
    active_turn_id = ""
    if controller is not None:
        active_turn_id = str(controller.turn_id or "").strip()
    if not active_turn_id:
        for run in list_active_session_work_runs():
            if str(run.get("sessionId") or "").strip() == conversation_id:
                active_turn_id = str(run.get("runId") or "").strip()
                break

    running = _is_session_running(conversation_id)
    signal = _record_chat_next_state_signal(
        session_id=conversation_id,
        turn_id=active_turn_id,
        source="user",
        kind="user_interrupt_guidance" if normalized_mode == "interrupt" else "user_guidance",
        polarity="neutral",
        mode="directive",
        related_event_code=(
            "conversation.user_interrupt_guidance_submitted"
            if normalized_mode == "interrupt"
            else "conversation.user_guidance_submitted"
        ),
        summary=guidance_text,
        metadata={
            "guidanceMode": normalized_mode,
            "guidanceLength": len(guidance_text),
            "sessionRunning": running,
            "willRequestStop": normalized_mode == "interrupt" and running,
        },
    )
    _record_session_guidance_event(
        conversation_id,
        mode=normalized_mode,
        turn_id=active_turn_id,
        signal_id=str((signal or {}).get("signalId") or ""),
        guidance_length=len(guidance_text),
        running=running,
    )

    if normalized_mode == "interrupt" and running:
        return request_stop_session_turn(conversation_id)

    _publish_session_detail_snapshot(conversation_id)
    return get_session_detail(conversation_id) or detail


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


def stream_session_events(session_id: str, initial_detail: dict[str, Any] | None = None):
    """Yield SSE events for one persisted chat session."""

    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise SessionNotFoundError(
            text_for(get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )
    detail = initial_detail or get_session_detail(conversation_id)
    if detail is None:
        raise SessionNotFoundError(
            text_for(get_web_language(), zh="未找到当前会话。", en="Session not found.")
        )

    subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_SESSION_STREAM_QUEUE_SIZE)
    _register_session_stream_subscriber(conversation_id, subscriber)
    try:
        yield _encode_sse_event(
            "session_detail",
            {
                "type": "session_detail",
                "sessionId": conversation_id,
                "detail": detail,
            },
        )
        while True:
            try:
                event = subscriber.get(timeout=_SESSION_STREAM_HEARTBEAT_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield _encode_sse_event(str(event.get("type") or "message"), event)
    finally:
        _unregister_session_stream_subscriber(conversation_id, subscriber)


def submit_session_message(
    session_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    *,
    attachment_ids: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    turn_mode: str = "",
    write_intent: bool | None = None,
    message_metadata: dict[str, Any] | None = None,
    message_source: str = "raw",
    include_started_turn_id: bool = False,
    lightweight_response: bool = False,
) -> dict:
    """Persist a user message and start a single web chat turn."""

    submit_started_at = _perf_counter()
    submit_timing_fields: dict[str, Any] = {}
    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    normalized_message_source = str(message_source or "").strip() or "raw"
    recent_image_reference_routing_enabled = normalized_message_source != "supervised_evolution"
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
    _validate_user_message_not_encoding_replacement(message, lang=lang)
    lock_wait_started_at = _perf_counter()
    with _CHAT_STATE_LOCK:
        lock_acquired_at = _perf_counter()
        submit_timing_fields["chatStateLockWaitMs"] = _elapsed_ms_between(lock_wait_started_at, lock_acquired_at)
        payload = load_chat_state(PROJECT_ROOT)
        _materialize_agent_directory_conversation_locked(payload, conversation_id, source="submit_session_message")
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_conversation_workspace_metadata(conversation)
        attachments = _resolve_session_image_attachments(
            conversation_id,
            attachment_ids or [],
            conversation=conversation,
        )
        session_references = _resolve_session_references(
            conversation_id,
            references or [],
            conversations=payload.get("conversations") or [],
            lang=lang,
        )
        active_task = _normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not _is_task_tool_backed_active_task(active_task):
            active_task = None
        explicit_recent_image_reference = (
            _has_recent_image_attachment_reference(message)
            if recent_image_reference_routing_enabled
            else False
        )
        contextual_recent_image_request = (
            {}
            if not recent_image_reference_routing_enabled or attachments or explicit_recent_image_reference
            else _image_context_request_for_retry(
                message,
                conversation=conversation,
            )
        )
        contextual_recent_image_prompt = str(contextual_recent_image_request.get("prompt") or "").strip()
        contextual_recent_image_artifact_ids = [
            str(item or "").strip()
            for item in list(contextual_recent_image_request.get("artifactIds") or [])
            if str(item or "").strip()
        ]
        recent_image_reference_prompt = message if explicit_recent_image_reference else contextual_recent_image_prompt
        recent_image_reference_requested = not attachments and bool(recent_image_reference_prompt)
        recent_image_reference_missing = False
        if recent_image_reference_requested:
            if contextual_recent_image_artifact_ids:
                attachments = _resolve_session_image_attachments(
                    conversation_id,
                    contextual_recent_image_artifact_ids,
                    conversation=conversation,
                )
                recent_image_reference_missing = not bool(attachments)
            elif explicit_recent_image_reference:
                recent_attachment = _find_recent_user_image_attachment(conversation)
                if recent_attachment:
                    attachments = _resolve_session_image_attachments(
                        conversation_id,
                        [str(recent_attachment.get("artifactId") or "").strip()],
                        conversation=conversation,
                    )
                else:
                    recent_image_reference_missing = True
            else:
                recent_image_reference_missing = True
        if not message and not attachments and not session_references:
            raise SessionValidationError(
                text_for(lang, zh="请输入本轮消息、添加图片或引用会话后再发送。", en="Enter a message, attach an image, or reference a session before sending.")
            )

        if _is_session_running(conversation_id):
            raise SessionBusyError(
                text_for(
                    lang,
                    zh="当前会话仍在运行，请等这一轮结束后再继续发送。",
                    en="This session is still running. Wait for the current turn to finish before sending again.",
                )
            )

        if normalized_message_source == "supervised_evolution":
            requested_leases = ["readonly_chat"]
        else:
            requested_leases = infer_chat_turn_leases(
                {
                    "content": message,
                    "mode": turn_mode,
                    "writeIntent": write_intent,
                    "activeTask": active_task,
                }
            )
        lease_decision = _check_chat_turn_lease_decision(requested_leases)
        if not lease_decision.allowed:
            localized_reason = _localize_lease_conflict(lease_decision.reason, lang=lang)
            _persist_session_preflight_rejection(
                conversation,
                message=message,
                reason=localized_reason,
                error_type="resource_lease_conflict",
                http_status=409,
                source="conversation.turn.lease_conflict",
                requested_leases=requested_leases,
                lease_conflicts=lease_decision.conflicts,
                lang=lang,
            )
            payload["updated_at"] = conversation.get("updated_at") or _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)
            raise SessionBusyError(localized_reason)

        _ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = _resolve_active_agent_for_turn(conversation_id, agent_id, lang=lang)
        previous_messages = normalize_chat_messages(conversation.get("messages") or [])
        skill_command = parse_skill_slash_command(message)
        skill_invocation = _skill_invocation_payload(skill_command) if skill_command is not None else None
        _reconcile_stale_session_ledger(conversation_id, reason="new_turn_submitted")
        turn_control = _create_session_turn_control(conversation_id)
        active_skill_contract = (
            _active_skill_contract_from_invocation(skill_invocation, turn_id=turn_control.turn_id)
            if skill_invocation
            else _active_skill_contract_from_conversation(conversation)
        )
        persisted_message_metadata = dict(message_metadata or {}) if isinstance(message_metadata, dict) else {}
        persisted_message_metadata.setdefault("turnId", turn_control.turn_id)
        if session_references:
            persisted_message_metadata["sessionReferences"] = session_references
        if skill_invocation:
            persisted_message_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
            if active_skill_contract is not None:
                conversation["active_skill_contract"] = active_skill_contract
        user_entry = _make_chat_message(
            "user",
            message,
            metadata=persisted_message_metadata,
            attachments=attachments,
            references=session_references,
        )
        if recent_image_reference_requested:
            user_entry.setdefault("metadata", {})
            user_entry["metadata"]["resolvedRecentImageReference"] = {
                "status": "missing" if recent_image_reference_missing else "resolved",
                "source": "explicit" if explicit_recent_image_reference else "contextual_retry",
                "prompt": trim_lines(recent_image_reference_prompt, max_lines=3),
                "artifactIds": [
                    str(item.get("artifactId") or "").strip()
                    for item in _normalize_message_attachments(attachments)
                    if str(item.get("artifactId") or "").strip()
                ],
            }
        conversation["messages"] = previous_messages + [user_entry]
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = user_entry["timestamp"]
        payload["active_conversation_id"] = conversation_id
        payload["updated_at"] = user_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _set_session_running(conversation_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        _persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=message,
            started_at=user_entry["timestamp"],
            updated_at=user_entry["timestamp"],
        )
        submit_timing_fields["chatStateLockedMs"] = _elapsed_ms_between(lock_acquired_at)
    _append_session_conversation_event(
        conversation_id,
        turn_control.turn_id,
        EVENT_TURN_STARTED,
        status="running",
        payload={
            "agentId": agent_id,
            "leases": requested_leases,
            "source": normalized_message_source,
        },
        source="submit_session_message",
    )
    _append_session_conversation_event(
        conversation_id,
        turn_control.turn_id,
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={
            "content": message,
            "attachments": _normalize_message_attachments(attachments),
            "references": _normalize_session_references(session_references),
            "source": normalized_message_source,
        },
        source="submit_session_message",
    )
    _set_session_waiting_live_output(conversation_id, turn_id=turn_control.turn_id)
    _record_session_cycle_message(
        conversation_id,
        user_entry,
        event="user_message",
        status="running",
    )
    _record_session_turn_started_event(
        conversation_id,
        turn_id=turn_control.turn_id,
        leases=requested_leases,
        user_message=message,
        raw_user_message=message,
        user_message_source=normalized_message_source,
        attachments=attachments,
    )
    if session_references:
        _record_session_turn_lifecycle_event(
            conversation_id,
            "session_references_attached",
            turn_id=turn_control.turn_id,
            outcome="recorded",
            fields={
                "referenceCount": len(session_references),
                "targetSessionIds": [str(item.get("sessionId") or "").strip() for item in session_references],
                "queryAllowed": True,
                "sendRequiresExplicitUserIntent": True,
            },
        )
    publish_started_at = _perf_counter()
    _publish_session_detail_snapshot(conversation_id)
    submit_timing_fields["initialSnapshotPublishMs"] = _elapsed_ms(publish_started_at)

    if recent_image_reference_missing and normalized_message_source != "agent_inbox":
        visible = _recent_image_attachment_missing_message(lang)
        _finish_image_attachment_routed_turn(
            conversation_id,
            turn_control.turn_id,
            {
                "status": "completed",
                "summary": visible,
                "raw_output": visible,
                "outcome": "needs_input",
                "metadata": {
                    "imageAttachmentRoute": "missing_recent_image",
                    "imageAttachmentIntent": "recent_image_reference",
                },
            },
            route="missing_recent_image",
            intent="recent_image_reference",
            agent_id=agent_id,
            attachments=[],
            leases=requested_leases,
            raw_user_message=message,
            fields={
                "recentImageReference": True,
                "resolvedRecentImageReference": False,
            },
            outcome="needs_input",
        )
        detail = get_session_detail(conversation_id) or {}
        if include_started_turn_id:
            detail["startedTurnId"] = turn_control.turn_id
        return detail
    if attachments and normalized_message_source != "agent_inbox":
        image_route_prompt = recent_image_reference_prompt or message
        image_route = _resolve_image_attachment_turn_route(image_route_prompt, agent_instance=agent)
        image_route_llm_slot = str(image_route.get("llm_slot") or "").strip() or SESSION_LLM_SLOT_DIALOGUE
        image_route_log_fields = {
            "supportsImageInput": image_route.get("supports_image_input"),
            "llmSlot": image_route_llm_slot,
            "llmModelId": str(image_route.get("model_id") or "").strip(),
            "dialogueModelId": agent_dialogue_model_id(agent),
            "visionModelId": agent_llm_model_id(agent, SESSION_LLM_SLOT_VISION),
            "modelName": image_route.get("model_name") or "",
            "recentImageReference": bool(recent_image_reference_requested),
            "resolvedRecentImageReference": bool(recent_image_reference_requested and not recent_image_reference_missing),
            "recentImageReferenceSource": "explicit" if explicit_recent_image_reference else "contextual_retry" if recent_image_reference_requested else "",
        }
        if image_route["route"] == "clarify":
            _finish_image_attachment_routed_turn(
                conversation_id,
                turn_control.turn_id,
                {
                    "status": "completed",
                    "summary": _image_attachment_clarification_message(lang),
                    "raw_output": _image_attachment_clarification_message(lang),
                    "outcome": "needs_input",
                    "metadata": {
                        "imageAttachmentRoute": "clarify",
                        "imageAttachmentIntent": image_route["intent"],
                    },
                },
                route="clarify",
                intent=image_route["intent"],
                agent_id=agent_id,
                attachments=attachments,
                leases=requested_leases,
                raw_user_message=message,
                fields=image_route_log_fields,
            )
            detail = get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail
        if image_route["route"] == "block_vision":
            visible = _image_input_unsupported_message(lang, model_name=str(image_route.get("model_name") or "").strip())
            _finish_image_attachment_routed_turn(
                conversation_id,
                turn_control.turn_id,
                {
                    "status": "failed_runtime",
                    "summary": visible,
                    "raw_output": visible,
                    "error": visible,
                    "outcome": "blocked",
                    "metadata": {
                        "imageAttachmentRoute": "block_vision",
                        "imageAttachmentIntent": image_route["intent"],
                        "supportsImageInput": image_route["supports_image_input"],
                    },
                },
                route="block_vision",
                intent=image_route["intent"],
                agent_id=agent_id,
                attachments=attachments,
                leases=requested_leases,
                raw_user_message=message,
                fields=image_route_log_fields,
                outcome="blocked",
                level="warning",
            )
            detail = get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail
        if image_route["route"] == "vision":
            _record_image_attachment_router_event(
                conversation_id,
                turn_id=turn_control.turn_id,
                route="vision",
                intent=image_route["intent"],
                outcome="scheduled",
                agent_id=agent_id,
                attachments=attachments,
                fields=image_route_log_fields,
            )

    if normalized_message_source == "agent_inbox":
        effective_user_message, user_message_source = message, normalized_message_source
    elif attachments:
        effective_user_message = recent_image_reference_prompt or message or text_for(
            lang,
            zh="请查看本轮图片附件并回答。",
            en="Please inspect the image attachment(s) from this turn and respond.",
        )
        user_message_source = "raw_with_attachments" if message else "attachments_only"
    elif normalized_message_source == "supervised_evolution":
        effective_user_message, user_message_source = message, normalized_message_source
    else:
        effective_user_message, user_message_source = _resolve_session_user_prompt(
            conversation_id,
            message,
            previous_messages,
            existing_task=active_task,
        )
        if effective_user_message == message and normalized_message_source != "raw":
            user_message_source = normalized_message_source
    reference_prompt_block = _session_reference_prompt_block(session_references)
    if reference_prompt_block:
        effective_user_message = "\n\n".join(part for part in [effective_user_message or message, reference_prompt_block] if part).strip()
        if not user_message_source or user_message_source == "raw":
            user_message_source = "raw_with_session_references" if message else "session_references_only"
    if effective_user_message != message:
        _record_session_user_message_filtered_event(
            conversation_id,
            turn_id=turn_control.turn_id,
            reason="non_meaningful_user_message",
            message=message,
            source=user_message_source,
        )
    if _is_continue_request(message):
        _record_chat_next_state_signal(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            source="user",
            kind="user_continues",
            polarity="neutral",
            mode="directive",
            related_event_code="conversation.user_continue_requested",
            summary=text_for(
                lang,
                zh="用户请求继续上一轮未完成任务。",
                en="The user requested continuation of the unfinished task.",
            ),
            metadata={
                "userMessageSource": user_message_source,
                "effectivePromptLength": len(effective_user_message),
            },
        )

    context = {
        "session_id": conversation_id,
        "turn_id": turn_control.turn_id,
        "turn_control": turn_control,
        "user_message": effective_user_message,
        "raw_user_message": message,
        "user_message_source": user_message_source,
        "attachments": attachments,
        "session_references": session_references,
        "history_messages": previous_messages,
        "mental_model_enabled": mental_model_enabled,
        "active_task": active_task,
        "agent_id": agent_id,
        "leases": requested_leases,
        "skill_invocation": skill_invocation,
        "active_skill_contract": active_skill_contract,
        "llm_slot": SESSION_LLM_SLOT_VISION if attachments else SESSION_LLM_SLOT_DIALOGUE,
        "submit_timing_fields": dict(submit_timing_fields),
        "submit_started_at_monotonic": submit_started_at,
    }
    _record_session_turn_scheduled_event(context)
    try:
        schedule_started_at = _perf_counter()
        _schedule_session_turn(context)
        submit_timing_fields["scheduleSubmitMs"] = _elapsed_ms(schedule_started_at)
    except Exception as exc:
        _persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=message,
            summary=f"{type(exc).__name__}: {exc}",
        )
        _set_session_running(conversation_id, False)
        _clear_session_turn_control(conversation_id)
        _persist_session_turn_failure(conversation_id, context, exc)
        _publish_session_detail_snapshot(conversation_id)
        raise
    if lightweight_response:
        return _accepted_session_turn_payload(
            conversation_id,
            turn_control.turn_id,
            status="running",
        )
    detail = get_session_detail(conversation_id) or {}
    if include_started_turn_id:
        detail["startedTurnId"] = turn_control.turn_id
    return detail


def _accepted_session_turn_payload(session_id: str, turn_id: str, *, status: str = "running") -> dict[str, Any]:
    return {
        "accepted": True,
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "status": str(status or "running").strip() or "running",
        "acceptedAt": _now_timestamp(),
    }


def submit_session_message_lightweight(
    session_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    *,
    attachment_ids: list[str] | None = None,
    references: list[dict[str, Any]] | None = None,
    turn_mode: str = "",
    write_intent: bool | None = None,
) -> dict[str, Any]:
    """Submit a user message and return the smallest accepted-turn payload."""

    detail = submit_session_message(
        session_id,
        content,
        content_utf8_base64=content_utf8_base64,
        mental_model_enabled=mental_model_enabled,
        attachment_ids=attachment_ids,
        references=references,
        turn_mode=turn_mode,
        write_intent=write_intent,
        include_started_turn_id=True,
        lightweight_response=True,
    )
    return detail


def wake_agent_for_inbox_message(message: dict[str, Any]) -> dict[str, Any]:
    """Start the target Agent's direct session so it can answer an inbox message."""

    message_id = str(message.get("messageId") or message.get("eventId") or "").strip()
    target_agent_id = str(message.get("targetAgentId") or "").strip()
    target_agent = get_agent(target_agent_id, include_archived=False) if target_agent_id else None
    archived_target_agent = None if target_agent else (get_agent(target_agent_id, include_archived=True) if target_agent_id else None)
    target_session_id = str(
        message.get("targetSessionId") or (target_agent or archived_target_agent or {}).get("directSessionId") or ""
    ).strip()
    delivery = {
        "wakeRequested": True,
        "wakeStatus": "skipped",
        "messageId": message_id,
        "targetAgentId": target_agent_id,
        "targetSessionId": target_session_id,
        "turnId": "",
        "reason": "",
    }
    if not target_agent:
        archived_status = str((archived_target_agent or {}).get("status") or "").strip().lower()
        if archived_status == "archived":
            delivery["wakeStatus"] = "skipped_archived_agent"
            delivery["reason"] = "target_agent_archived"
            _record_agent_inbox_wake_event("agent_inbox.wake_skipped_archived_agent", message, delivery, level="warning")
        else:
            delivery["wakeStatus"] = "skipped_missing_agent"
            delivery["reason"] = "target_agent_not_found"
            _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
        return delivery
    target_metadata = target_agent.get("metadata") if isinstance(target_agent.get("metadata"), dict) else {}
    delegation_decision = evaluate_delegation_wake_policy(target_metadata.get("delegationPolicy"), agent_id=target_agent_id)
    if not delegation_decision.allowed:
        delivery["wakeStatus"] = "skipped_policy_blocked"
        delivery["reason"] = delegation_decision.reason
        _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
        return delivery
    if not target_session_id:
        delivery["wakeStatus"] = "skipped_no_direct_session"
        delivery["reason"] = "target_agent_has_no_direct_session"
        _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
        return delivery
    if _is_session_running(target_session_id):
        delivery["wakeStatus"] = "skipped_busy"
        delivery["reason"] = "target_session_busy"
        _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
        return delivery

    message_metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    research_org_metadata = {
        "researchOrgMessageId": str(message_metadata.get("researchOrgMessageId") or "").strip(),
        "researchOrgDeliveryMode": str(message_metadata.get("researchOrgDeliveryMode") or "").strip(),
        "researchOrgMessageType": str(message_metadata.get("researchOrgMessageType") or "").strip(),
        "researchOrgIntent": str(message_metadata.get("researchOrgIntent") or "").strip(),
        "communicationEdgeId": str(message_metadata.get("communicationEdgeId") or "").strip(),
    }
    prompt = _format_agent_inbox_wake_prompt(message)
    try:
        detail = submit_session_message(
            target_session_id,
            prompt,
            turn_mode="agent_inbox",
            write_intent=False,
            message_metadata={
                "kind": "agent_inbox_message",
                "messageId": message_id,
                "inboxKind": str(message.get("kind") or "").strip(),
                "threadId": str(message.get("threadId") or "").strip(),
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "sourceAgentCode": str(message.get("sourceAgentCode") or "").strip(),
                "sourceAgentName": str(message.get("sourceAgentName") or "").strip(),
                "sourceSessionId": str(message.get("sourceSessionId") or "").strip(),
                "targetAgentId": target_agent_id,
                "targetAgentCode": str(message.get("targetAgentCode") or "").strip(),
                "targetAgentName": str(message.get("targetAgentName") or "").strip(),
                "targetSessionId": target_session_id,
                **{key: value for key, value in research_org_metadata.items() if value},
            },
            message_source="agent_inbox",
            include_started_turn_id=True,
        )
    except SessionBusyError:
        delivery["wakeStatus"] = "skipped_busy"
        delivery["reason"] = "target_session_busy"
        _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
        return delivery
    except (SessionNotFoundError, SessionValidationError) as exc:
        delivery["wakeStatus"] = "skipped_invalid_session"
        delivery["reason"] = type(exc).__name__
        _record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
        return delivery

    turn_id = str(detail.get("startedTurnId") or "").strip()
    try:
        consume_agent_inbox_message(
            target_agent_id,
            message_id,
            consumed_by_session_id=target_session_id,
            consumed_by_turn_id=turn_id,
        )
    except Exception as exc:
        delivery["wakeStatus"] = "started_consume_failed"
        delivery["reason"] = type(exc).__name__
        delivery["turnId"] = turn_id
        _record_agent_inbox_wake_event("agent_inbox.wake_started_consume_failed", message, delivery, level="warning")
        return delivery

    delivery["wakeStatus"] = "started"
    delivery["turnId"] = turn_id
    _record_agent_inbox_wake_event("agent_inbox.wake_started", message, delivery, level="info")
    return delivery


def edit_and_resubmit_session_message(
    session_id: str,
    message_id: str,
    content: str,
    content_utf8_base64: str = "",
    mental_model_enabled: bool | None = None,
    *,
    turn_mode: str = "",
    write_intent: bool | None = None,
) -> dict:
    """Replace the latest user message, truncate later turns, and start a new turn."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    target_message_id = str(message_id or "").strip()
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
    if not target_message_id:
        raise SessionValidationError(text_for(lang, zh="请选择要重新编辑的消息。", en="Choose a message to edit."))
    if not message:
        raise SessionValidationError(
            text_for(lang, zh="请输入重新发送的消息。", en="Enter the edited message before sending.")
        )
    _validate_user_message_not_encoding_replacement(message, lang=lang)

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_conversation_workspace_metadata(conversation)

        previous_messages = normalize_chat_messages(conversation.get("messages") or [])
        skill_command = parse_skill_slash_command(message)
        skill_invocation = _skill_invocation_payload(skill_command) if skill_command is not None else None
        target_index = _find_user_message_index_by_api_id(conversation_id, previous_messages, target_message_id)
        if target_index < 0:
            raise SessionValidationError(
                text_for(lang, zh="只能重新编辑历史用户消息。", en="Only historical user messages can be edited and resent.")
            )
        latest_user_index = _latest_user_message_index(previous_messages)
        if target_index != latest_user_index:
            latest_message_id = ""
            if latest_user_index >= 0:
                latest_message_id = str(previous_messages[latest_user_index].get("id") or "").strip()
            _record_session_message_edit_resubmit_rejected_event(
                conversation_id,
                target_message_id=target_message_id,
                reason="not_latest_user_message",
                latest_message_id=latest_message_id,
                target_preview=previous_messages[target_index].get("content") or "",
            )
            raise SessionValidationError(
                text_for(lang, zh="只能重新编辑最新一条用户消息。", en="Only the latest user message can be edited and resent.")
            )

        active_task = _normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not _is_task_tool_backed_active_task(active_task):
            active_task = None
        requested_leases = infer_chat_turn_leases(
            {
                "content": message,
                "mode": turn_mode,
                "writeIntent": write_intent,
                "activeTask": active_task,
            }
        )
        lease_decision = _check_chat_turn_lease_decision(requested_leases)
        if not lease_decision.allowed:
            localized_reason = _localize_lease_conflict(lease_decision.reason, lang=lang)
            _persist_session_preflight_rejection(
                conversation,
                message=message,
                reason=localized_reason,
                error_type="resource_lease_conflict",
                http_status=409,
                source="conversation.turn.lease_conflict",
                requested_leases=requested_leases,
                lease_conflicts=lease_decision.conflicts,
                lang=lang,
            )
            payload["updated_at"] = conversation.get("updated_at") or _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)
            raise SessionBusyError(localized_reason)

        _ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = _resolve_active_agent_for_turn(conversation_id, agent_id, lang=lang)
        original_entry = dict(previous_messages[target_index])
        original_metadata = original_entry.get("metadata") if isinstance(original_entry.get("metadata"), dict) else {}
        original_was_slash_skill = isinstance(original_metadata.get("slashSkillCommand"), dict)
        superseded_turn_id = ""
        if _is_session_running(conversation_id):
            superseded_turn_id = _supersede_active_session_turn_for_edit(conversation_id, lang=lang)
        turn_control = _create_session_turn_control(conversation_id)
        active_skill_contract = (
            _active_skill_contract_from_invocation(skill_invocation, turn_id=turn_control.turn_id)
            if skill_invocation
            else _active_skill_contract_from_conversation(conversation)
        )
        user_metadata = {}
        if skill_invocation:
            user_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
            if active_skill_contract is not None:
                conversation["active_skill_contract"] = active_skill_contract
        elif original_was_slash_skill:
            active_skill_contract = None
            conversation.pop("active_skill_contract", None)
            conversation.pop("activeSkillContract", None)
        user_entry = _make_chat_message("user", message, metadata=user_metadata)
        edited_messages = previous_messages[:target_index] + [user_entry]
        conversation["messages"] = edited_messages
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = user_entry["timestamp"]
        payload["active_conversation_id"] = conversation_id
        payload["updated_at"] = user_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _set_session_running(conversation_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        _persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=message,
            started_at=user_entry["timestamp"],
            updated_at=user_entry["timestamp"],
        )

    _set_session_waiting_live_output(conversation_id, turn_id=turn_control.turn_id)
    _record_session_message_edit_resubmit_event(
        conversation_id,
        target_message_id=target_message_id,
        turn_id=turn_control.turn_id,
        truncated_count=max(0, len(previous_messages) - target_index - 1),
        original_content=original_entry.get("content") or "",
        edited_content=message,
    )
    _record_chat_next_state_signal(
        session_id=conversation_id,
        turn_id=turn_control.turn_id,
        source="user",
        kind="assistant_output_edited",
        polarity="neutral",
        mode="directive",
        related_event_code="conversation.message_edited_resubmitted",
        summary=text_for(
            lang,
            zh="用户编辑最新消息并重新提交，后续 assistant 输出被截断重跑。",
            en="The user edited the latest message and resubmitted, truncating later assistant output.",
        ),
        metadata={
            "messageId": target_message_id,
            "truncatedMessageCount": max(0, len(previous_messages) - target_index - 1),
            "originalLength": len(str(original_entry.get("content") or "")),
            "editedLength": len(message),
            "supersededTurnId": superseded_turn_id,
        },
    )
    _record_session_cycle_message(
        conversation_id,
        user_entry,
        event="user_message_edited_resubmitted",
        status="running",
    )
    _record_session_turn_started_event(
        conversation_id,
        turn_id=turn_control.turn_id,
        leases=requested_leases,
        user_message=message,
        raw_user_message=message,
        user_message_source="raw",
    )
    _publish_session_detail_snapshot(conversation_id)

    effective_user_message, user_message_source = _resolve_session_user_prompt(
        conversation_id,
        message,
        edited_messages[:target_index],
        existing_task=active_task,
    )
    if effective_user_message != message:
        _record_session_user_message_filtered_event(
            conversation_id,
            turn_id=turn_control.turn_id,
            reason="non_meaningful_user_message",
            message=message,
            source=user_message_source,
        )

    context = {
        "session_id": conversation_id,
        "turn_id": turn_control.turn_id,
        "turn_control": turn_control,
        "user_message": effective_user_message,
        "raw_user_message": message,
        "user_message_source": user_message_source,
        "history_messages": edited_messages[:target_index],
        "mental_model_enabled": mental_model_enabled,
        "active_task": active_task,
        "agent_id": agent_id,
        "skill_invocation": skill_invocation,
        "active_skill_contract": active_skill_contract,
        "llm_slot": SESSION_LLM_SLOT_DIALOGUE,
    }
    _record_session_turn_scheduled_event(context)
    try:
        _schedule_session_turn(context)
    except Exception as exc:
        _persist_chat_turn_work_run(
            session_id=conversation_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=message,
            summary=f"{type(exc).__name__}: {exc}",
        )
        _set_session_running(conversation_id, False)
        _clear_session_turn_control(conversation_id)
        _persist_session_turn_failure(conversation_id, context, exc)
        _publish_session_detail_snapshot(conversation_id)
        raise
    return get_session_detail(conversation_id) or {}


def _resolve_user_message_content(content: str, *, content_utf8_base64: str = "") -> str:
    encoded = str(content_utf8_base64 or "").strip()
    if not encoded:
        return str(content or "").strip()
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return str(content or "").strip()
    return decoded.strip()


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


def _load_conversations(
    *,
    repair: bool = True,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    lightweight: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    with _CHAT_STATE_LOCK, chat_state_transaction(PROJECT_ROOT):
        payload = load_chat_state(PROJECT_ROOT)
        if repair:
            payload = _repair_stale_running_conversations(payload)
        active_id = str(payload.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
        conversations: list[dict[str, Any]] = []
        changed = False
        agent_by_id = agent_by_id if agent_by_id is not None else _agent_lookup_for_conversations()
        for raw in list(payload.get("conversations") or []):
            if repair and isinstance(raw, dict):
                changed = _ensure_conversation_workspace_metadata(raw) or changed
                changed = _ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
            conversation = _normalize_conversation(
                raw,
                agent_by_id=agent_by_id,
                ensure_workspace=repair,
                lightweight=lightweight,
            )
            if conversation is not None:
                conversations.append(conversation)
        if repair and changed:
            payload["updated_at"] = _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)
        return active_id or DEFAULT_CHAT_CONVERSATION_ID, conversations


def _load_conversation_detail_target(
    session_id: str,
    *,
    payload: dict[str, Any] | None = None,
    repair: bool = True,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    payload = payload if isinstance(payload, dict) else load_chat_state(PROJECT_ROOT)
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    agent_by_id = agent_by_id if agent_by_id is not None else _agent_lookup_for_conversations()
    changed = False
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        raw_session_id = str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
        if raw_session_id != normalized_session_id:
            continue
        if repair:
            changed = _repair_stale_running_conversation(raw) or changed
            changed = _ensure_conversation_workspace_metadata(raw) or changed
            changed = _ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
        conversation = _normalize_conversation(raw, agent_by_id=agent_by_id, ensure_workspace=repair)
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


def _append_agent_directory_conversations(
    conversations: list[dict[str, Any]],
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_session_id = {
        str(item.get("id") or "").strip(): item
        for item in conversations
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    result = list(conversations)
    try:
        agents = list((agent_by_id if agent_by_id is not None else _agent_lookup_for_conversations()).values())
    except Exception:
        return result
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        session_id = str(agent.get("directSessionId") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if not session_id or not agent_id or session_id in by_session_id:
            continue
        conversation = _agent_directory_conversation_stub(agent, session_id=session_id)
        result.append(conversation)
        by_session_id[session_id] = conversation
        _record_agent_directory_conversation_index_event(agent, session_id=session_id)
    return result


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


def _ensure_agent_directory_conversation_materialized(session_id: str, *, source: str) -> bool:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        changed = _materialize_agent_directory_conversation_locked(payload, normalized_session_id, source=source)
        if changed:
            save_chat_state(PROJECT_ROOT, payload)
        return changed


def _materialize_agent_directory_conversation_locked(payload: dict[str, Any], session_id: str, *, source: str) -> bool:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or _find_conversation_entry(payload, normalized_session_id) is not None:
        return False
    agent = _agent_for_direct_session(normalized_session_id)
    if not agent:
        return False
    conversation = _agent_directory_conversation_record(agent, session_id=normalized_session_id)
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        conversations = []
        payload["conversations"] = conversations
    conversations.append(conversation)
    payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
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
    conversation = _make_empty_conversation(session_id, title=display_name, timestamp=timestamp)
    conversation["agent_id"] = str(agent.get("agentId") or "").strip()
    conversation["agentId"] = str(agent.get("agentId") or "").strip()
    _ensure_conversation_workspace_metadata(conversation)
    return conversation


def mark_direct_session_agent_deleted(
    session_id: str,
    *,
    agent_id: str,
    agent_display_name: str = "",
    previous_status: str = "",
    include_restore_token: bool = False,
) -> dict[str, Any]:
    """Keep direct-session history while preventing Agent repair from recreating a purged Agent."""

    normalized_session_id = str(session_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_session_id:
        return {
            "changed": False,
            "sessionId": "",
            "agentId": normalized_agent_id,
            "reason": "no_direct_session",
        }
    changed = False
    found = False
    restore_token: dict[str, Any] | None = None
    now = _now_timestamp()
    try:
        with _CHAT_STATE_LOCK:
            payload = load_chat_state(PROJECT_ROOT)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            if include_restore_token:
                restore_token = {
                    "sessionId": normalized_session_id,
                    "agentId": normalized_agent_id,
                    "previousConversation": None,
                    "previousActiveConversationId": str(payload.get("active_conversation_id") or "").strip(),
                    "previousUpdatedAt": str(payload.get("updated_at") or "").strip(),
                    "previousVersion": payload.get("version"),
                }
            for raw in conversations:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip() != normalized_session_id:
                    continue
                found = True
                if restore_token is not None:
                    restore_token["previousConversation"] = copy.deepcopy(raw)
                changed = _mark_conversation_agent_deleted(
                    raw,
                    session_id=normalized_session_id,
                    agent_id=normalized_agent_id,
                    agent_display_name=agent_display_name,
                    previous_status=previous_status,
                    timestamp=now,
                ) or changed
                break
            if not found:
                conversation = _make_empty_conversation(
                    normalized_session_id,
                    title=agent_display_name or normalized_session_id,
                    timestamp=now,
                )
                _ensure_conversation_workspace_metadata(conversation)
                _mark_conversation_agent_deleted(
                    conversation,
                    session_id=normalized_session_id,
                    agent_id=normalized_agent_id,
                    agent_display_name=agent_display_name,
                    previous_status=previous_status,
                    timestamp=now,
                )
                conversations.append(conversation)
                changed = True
            if changed:
                payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
                payload["updated_at"] = now
                save_chat_state(PROJECT_ROOT, payload)
    except Exception as exc:
        result = {
            "changed": False,
            "sessionId": normalized_session_id,
            "agentId": normalized_agent_id,
            "agentStatusCode": "",
            "historyRetention": "unknown",
            "reason": "tombstone_failed",
            "errorType": type(exc).__name__,
        }
        _record_direct_session_agent_deleted_event(result, previous_status=previous_status, created_tombstone=False, level="error")
        return result
    if changed:
        _invalidate_session_list_cache()
    result = {
        "changed": changed,
        "sessionId": normalized_session_id,
        "agentId": normalized_agent_id,
        "agentStatusCode": "deleted_agent",
        "historyRetention": "preserved_tombstone",
        "reason": "agent_purged",
    }
    if restore_token is not None:
        restore_token["createdConversation"] = not found
        result["restoreToken"] = restore_token
    _record_direct_session_agent_deleted_event(result, previous_status=previous_status, created_tombstone=not found)
    return result


def restore_direct_session_agent_deleted_tombstone(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    """Restore a direct-session conversation after a failed pre-purge tombstone."""

    token = restore_token if isinstance(restore_token, dict) else {}
    normalized_session_id = str(token.get("sessionId") or "").strip()
    normalized_agent_id = str(token.get("agentId") or "").strip()
    if not normalized_session_id:
        return {"changed": False, "sessionId": "", "agentId": normalized_agent_id, "reason": "missing_restore_session"}
    changed = False
    try:
        with _CHAT_STATE_LOCK:
            payload = load_chat_state(PROJECT_ROOT)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            current_index = -1
            for index, raw in enumerate(conversations):
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip() == normalized_session_id:
                    current_index = index
                    break
            previous_conversation = token.get("previousConversation")
            if isinstance(previous_conversation, dict):
                restored = copy.deepcopy(previous_conversation)
                if current_index >= 0:
                    if conversations[current_index] != restored:
                        conversations[current_index] = restored
                        changed = True
                else:
                    conversations.append(restored)
                    changed = True
            elif current_index >= 0 and _conversation_agent_deleted_tombstone_matches(
                conversations[current_index],
                agent_id=normalized_agent_id,
            ):
                conversations.pop(current_index)
                changed = True
            previous_active = str(token.get("previousActiveConversationId") or "").strip()
            if previous_active and payload.get("active_conversation_id") != previous_active:
                payload["active_conversation_id"] = previous_active
                changed = True
            if changed:
                previous_updated_at = str(token.get("previousUpdatedAt") or "").strip()
                if previous_updated_at:
                    payload["updated_at"] = previous_updated_at
                else:
                    payload["updated_at"] = _now_timestamp()
                previous_version = token.get("previousVersion")
                if isinstance(previous_version, int):
                    payload["version"] = previous_version
                else:
                    payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
                save_chat_state(PROJECT_ROOT, payload)
    except Exception as exc:
        result = {
            "changed": False,
            "sessionId": normalized_session_id,
            "agentId": normalized_agent_id,
            "reason": "restore_failed",
            "errorType": type(exc).__name__,
        }
        _record_direct_session_agent_deleted_rollback_event(result, level="error")
        return result
    if changed:
        _invalidate_session_list_cache()
    result = {
        "changed": changed,
        "sessionId": normalized_session_id,
        "agentId": normalized_agent_id,
        "reason": "restored",
    }
    _record_direct_session_agent_deleted_rollback_event(result)
    return result


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


def _agent_directory_conversation_stub(agent: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
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
    conversation["messages"] = normalize_chat_messages(conversation.get("messages") or [])
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


def _normalize_session_runtime_notices(items: Any) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(list(items or []), start=1):
        notice = _normalize_session_runtime_notice(raw, index=index)
        if not notice:
            continue
        dedupe_key = (
            str(notice.get("kind") or ""),
            str(notice.get("message") or ""),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        notices.append(notice)
    return notices[-8:]


def _append_session_runtime_notice(items: Any, notice: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalize_session_runtime_notices([*list(items or []), notice])


def _not_called_llm_usage(*, recorded_at: str = "") -> dict[str, Any]:
    return {
        "source": "not_called",
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
    conversation["last_llm_usage"] = _not_called_llm_usage(recorded_at=timestamp)
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


def _runtime_notices_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for index, message in enumerate(list(messages or []), start=1):
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        if role != "assistant" or not _looks_like_runtime_failure_notice(content):
            continue
        if _has_visible_message_after_index(messages, index - 1):
            continue
        notices.append(
            {
                "id": f"legacy-runtime-notice-{index}",
                "kind": "turn_recovered" if "中断" in content or "interrupted" in content.lower() else "runtime_notice",
                "level": "warning",
                "message": content,
                "timestamp": str(message.get("timestamp") or "").strip(),
                "source": "legacy_assistant_message",
            }
        )
    return _normalize_session_runtime_notices(notices)


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


def _has_visible_message_after_index(messages: list[dict[str, Any]], index: int) -> bool:
    for later in list(messages or [])[index + 1:]:
        role = str(later.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(later.get("content") or "").strip()
        if not content or _looks_like_runtime_failure_notice(content):
            continue
        return True
    return False


def _filter_runtime_notice_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        message
        for message in list(messages or [])
        if not (
            str(message.get("role") or "").strip().lower() == "assistant"
            and _looks_like_runtime_failure_notice(message.get("content") or "")
        )
    ]


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


def _normalize_conversation(
    raw: Any,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
    ensure_workspace: bool = True,
    lightweight: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    conversation_id = str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return None
    workspace_path = _session_workspace_relative_path(conversation_id)
    if ensure_workspace:
        _ensure_session_workspace(conversation_id)
    title = str(raw.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip() or DEFAULT_CHAT_CONVERSATION_TITLE
    agent_id = str(raw.get("agent_id") or raw.get("agentId") or "").strip()
    agent = _agent_from_lookup(agent_by_id, agent_id) if agent_id else None
    agent_lookup_checked = agent_by_id is not None
    missing_agent_id = str(raw.get("agent_missing_id") or raw.get("agentMissingId") or "").strip()
    agent_missing = bool(raw.get("agentMissing"))
    agent_status_code = str(raw.get("agentStatusCode") or "").strip()
    agent_direct_session_mismatch = bool(raw.get("agentDirectSessionMismatch"))
    agent_primary_direct_session_id = str(raw.get("agentPrimaryDirectSessionId") or "").strip()
    if agent and str(agent.get("directSessionId") or "").strip() != conversation_id:
        agent_direct_session_mismatch = True
        agent_primary_direct_session_id = str(agent.get("directSessionId") or "").strip()
    elif agent and str(agent.get("directSessionId") or "").strip() == conversation_id:
        agent_direct_session_mismatch = False
        agent_primary_direct_session_id = ""
    elif agent_id and agent_lookup_checked and agent is None:
        missing_agent_id = agent_id
        agent_missing = True
        agent_status_code = "missing_agent"
    if lightweight:
        messages = _normalize_latest_preview_messages(conversation_id, raw.get("messages") or [])
        visible_runtime_notices: list[dict[str, Any]] = []
    else:
        raw_messages = _normalize_messages(conversation_id, raw.get("messages") or [])
        messages = _filter_runtime_notice_messages(raw_messages)
        runtime_notices = _normalize_session_runtime_notices(
            raw.get("runtime_notices") or raw.get("runtimeNotices") or []
        )
        visible_runtime_notices = _visible_session_runtime_notices(
            [*runtime_notices, *_runtime_notices_from_messages(raw_messages)],
            messages,
        )
    last_turn_status = str(raw.get("last_turn_status") or "").strip().lower()
    last_turn_error = _normalize_session_turn_error(raw.get("last_turn_error") or raw.get("lastTurnError"))
    last_llm_usage = _normalize_turn_llm_usage(raw.get("last_llm_usage") or raw.get("lastLlmUsage"))
    last_context_composition = _normalize_session_context_composition(
        raw.get("last_context_composition") or raw.get("lastContextComposition")
    )
    active_skill_contract = normalize_active_skill_contract(
        raw.get("active_skill_contract") or raw.get("activeSkillContract")
    )
    last_cache_composition = _normalize_session_cache_composition(
        raw.get("last_cache_composition") or raw.get("lastCacheComposition")
    )
    session_kind = _normalize_session_kind(raw.get("session_kind") or raw.get("sessionKind"))
    parent_session_id = str(raw.get("parent_session_id") or raw.get("parentSessionId") or "").strip()
    if session_kind == "main":
        parent_session_id = ""
    root_session_id = str(raw.get("root_session_id") or raw.get("rootSessionId") or "").strip()
    if not root_session_id:
        root_session_id = parent_session_id if session_kind == "child" and parent_session_id else conversation_id
    child_session_ids = _normalize_string_list(raw.get("child_session_ids") or raw.get("childSessionIds"))
    active_child_session_id = str(raw.get("active_child_session_id") or raw.get("activeChildSessionId") or "").strip()
    task_title = trim_lines(raw.get("task_title") or raw.get("taskTitle") or title, max_lines=1).strip() or title
    handoff_context = _normalize_child_handoff_context(raw.get("handoff_context") or raw.get("handoffContext"))
    result_card = _normalize_child_result_card(raw.get("result_card") or raw.get("resultCard"))
    child_status = str(raw.get("child_status") or raw.get("childStatus") or "").strip().lower()
    if session_kind == "child" and last_turn_status:
        child_status = last_turn_status
    updated_at = (
        str(raw.get("updated_at") or "").strip()
        or _latest_message_timestamp(messages)
    )
    active_task = raw.get("active_task")
    if not isinstance(active_task, dict):
        active_task = raw.get("activeTask")
    if not isinstance(active_task, dict):
        active_task = None
    return {
        "id": conversation_id,
        "title": title,
        "agentId": agent_id,
        "agentMissingId": missing_agent_id,
        "agentMissing": agent_missing,
        "agentStatusCode": agent_status_code,
        "agentDirectSessionMismatch": agent_direct_session_mismatch,
        "agentPrimaryDirectSessionId": agent_primary_direct_session_id,
        "workspacePath": workspace_path,
        "messages": messages,
        "runtimeNotices": visible_runtime_notices,
        "lastTurnStatus": last_turn_status,
        "lastTurnError": last_turn_error,
        "lastLlmUsage": last_llm_usage,
        "lastContextComposition": last_context_composition,
        "activeSkillContract": active_skill_contract,
        "lastCacheComposition": last_cache_composition,
        "sessionKind": session_kind,
        "hiddenFromIndex": bool(raw.get("hidden_from_index") or raw.get("hiddenFromIndex")),
        "parentSessionId": parent_session_id,
        "rootSessionId": root_session_id,
        "childSessionIds": child_session_ids,
        "activeChildSessionId": active_child_session_id,
        "taskTitle": task_title,
        "handoffContext": handoff_context,
        "resultCard": result_card,
        "childStatus": child_status,
        "updatedAt": updated_at,
        "activeTask": dict(active_task or {}) if isinstance(active_task, dict) else None,
        "_agent": dict(agent) if isinstance(agent, dict) else None,
        "_agentLookupChecked": bool(agent_lookup_checked),
    }


def _normalize_messages(conversation_id: str, items: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(list(items or []), start=1):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        raw_metadata = raw.get("metadata")
        if (
            role == "assistant"
            and isinstance(raw_metadata, dict)
            and str(raw_metadata.get("kind") or "").strip() == "checkpoint"
        ):
            continue
        content = _sanitize_message_content(role, raw.get("content") or "")
        thought = _normalize_message_thought(raw, role=role)
        mental_snapshot = _normalize_mental_snapshot(raw.get("mental_snapshot") or raw.get("mentalSnapshot"))
        tool_calls = _normalize_message_tool_calls(raw.get("tool_calls") or raw.get("toolCalls") or raw.get("tools") or [])
        feedback_events = _normalize_message_feedback_events(raw.get("feedback_events") or raw.get("feedbackEvents") or [])
        attachments = _normalize_message_attachments(raw.get("attachments") or raw.get("imageAttachments") or [])
        references = _normalize_session_references(raw.get("references") or (raw.get("metadata") or {}).get("sessionReferences") or [])
        if not content and not thought and mental_snapshot is None and not tool_calls and not feedback_events and not attachments and not references:
            continue
        entry: dict[str, Any] = {
            "id": f"{conversation_id}-message-{index}",
            "role": role,
            "content": content,
            "timestamp": str(raw.get("timestamp") or "").strip(),
        }
        if thought:
            entry["thought"] = thought
        if mental_snapshot is not None:
            entry["mentalSnapshot"] = mental_snapshot
        if tool_calls:
            entry["toolCalls"] = tool_calls
        if feedback_events:
            entry["feedbackEvents"] = feedback_events
        if attachments:
            entry["attachments"] = attachments
        if references:
            entry["references"] = references
        metadata = raw_metadata
        if isinstance(metadata, dict) and metadata:
            entry["metadata"] = dict(metadata)
            if role == "assistant" and str(metadata.get("kind") or "").strip() == "turn_error":
                entry["content"] = _complete_turn_error_visible_content(entry["content"], metadata)
        messages.append(entry)
    return _dedupe_turn_error_messages(messages)


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


def _normalize_child_handoff_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "source": str(value.get("source") or "").strip(),
        "parentSessionId": str(value.get("parentSessionId") or value.get("parent_session_id") or "").strip(),
        "sourceSessionId": str(value.get("sourceSessionId") or value.get("source_session_id") or "").strip(),
        "parentMessageId": str(value.get("parentMessageId") or value.get("parent_message_id") or "").strip(),
        "triggeringUserMessage": trim_lines(
            value.get("triggeringUserMessage") or value.get("triggering_user_message") or "",
            max_lines=8,
        ),
        "splitReason": trim_lines(value.get("splitReason") or value.get("split_reason") or "", max_lines=4),
        "inheritedFacts": [
            trim_lines(item, max_lines=2)
            for item in _normalize_string_list(value.get("inheritedFacts") or value.get("inherited_facts"))
        ],
        "relevantFiles": _normalize_string_list(value.get("relevantFiles") or value.get("relevant_files")),
        "relevantLogs": _normalize_string_list(value.get("relevantLogs") or value.get("relevant_logs")),
        "constraints": [trim_lines(item, max_lines=2) for item in _normalize_string_list(value.get("constraints"))],
        "excludedContextSummary": trim_lines(
            value.get("excludedContextSummary") or value.get("excluded_context_summary") or "",
            max_lines=4,
        ),
    }


def _normalize_child_result_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    title = trim_lines(value.get("title") or "", max_lines=1).strip()
    summary = trim_lines(value.get("summary") or "", max_lines=4).strip()
    if not title and not summary:
        return None
    return {
        "status": str(value.get("status") or "").strip(),
        "title": title,
        "summary": summary,
        "changedFiles": _normalize_string_list(value.get("changedFiles") or value.get("changed_files")),
        "validations": [
            trim_lines(item, max_lines=2)
            for item in _normalize_string_list(value.get("validations"))
        ],
        "nextStep": trim_lines(value.get("nextStep") or value.get("next_step") or "", max_lines=2),
        "updatedAt": str(value.get("updatedAt") or value.get("updated_at") or "").strip(),
    }


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


def _history_messages_for_agent_seed(items: Any) -> list[dict[str, Any]]:
    """Build the prompt history view without transient runtime failure notices."""

    filtered: list[dict[str, Any]] = []
    drop_assistant_until_next_user = False
    for item in normalize_chat_messages(items or []):
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
        summary = trim_lines(reference.get("summary") or _latest_message_summary(target.get("messages") or []), max_lines=2)
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


def _active_task_to_api(value: dict[str, Any] | None) -> dict[str, Any] | None:
    task = _normalize_session_active_task(value)
    if not task:
        return None
    if not _is_task_tool_backed_active_task(task):
        return None
    metadata = dict(task.get("metadata") or {}) if isinstance(task.get("metadata"), dict) else {}
    return {
        "taskId": str(task.get("task_id") or "").strip(),
        "kind": str(task.get("kind") or "").strip(),
        "status": str(task.get("status") or "").strip(),
        "title": str(task.get("title") or "").strip(),
        "goal": str(task.get("goal") or "").strip(),
        "readFiles": list(task.get("read_files") or []),
        "changedFiles": list(task.get("changed_files") or []),
        "verificationStatus": str(task.get("verification_status") or "").strip(),
        "verificationSummary": str(task.get("verification_summary") or "").strip(),
        "latestSummary": str(task.get("latest_summary") or "").strip(),
        "nextAction": str(task.get("next_action") or "").strip(),
        "lastUserMessage": str(task.get("last_user_message") or "").strip(),
        "turnCount": _coerce_nonnegative_int(task.get("turn_count") or 0),
        "resumeCount": _coerce_nonnegative_int(task.get("resume_count") or 0),
        "createdAt": str(task.get("created_at") or "").strip(),
        "updatedAt": str(task.get("updated_at") or "").strip(),
        "defaultFileContext": str(task.get("default_file_context") or "").strip(),
        "previewTabs": list(task.get("preview_tabs") or []),
        "activePreviewPath": str(task.get("active_preview_path") or "").strip(),
        "metadata": metadata,
    }


def _agent_inbox_pending_count_for_summary(agent: dict[str, Any] | None) -> int:
    if not isinstance(agent, dict):
        return 0
    inbox_path = agent_directory_service._agent_workspace_event_path(
        agent,
        "agent_inbox_messages.jsonl",
    )
    return agent_directory_service._count_jsonl_matching_status(
        inbox_path,
        status="pending",
    )


def _build_session_summary(conversation: dict[str, Any], *, hydrate_agent: bool = True) -> dict[str, Any]:
    status = _conversation_phase(conversation["id"], conversation)
    summary = _latest_message_summary(conversation.get("messages") or [])
    updated_at = str(conversation.get("updatedAt") or "").strip()
    agent_id = str(conversation.get("agentId") or "").strip()
    cached_agent = conversation.get("_agent")
    agent = cached_agent if isinstance(cached_agent, dict) else (get_agent(agent_id) if agent_id and hydrate_agent else None)
    agent_lookup_checked = bool(conversation.get("_agentLookupChecked"))
    agent_workspace_path = str((agent or {}).get("workspacePath") or "").strip()
    agent_code = str((agent or {}).get("agentCode") or "").strip()
    agent_avatar_image_path = str((agent or {}).get("avatarImagePath") or "").strip()
    agent_avatar_image_url = str((agent or {}).get("avatarImageUrl") or "").strip()
    agent_primary_mode = str((agent or {}).get("primaryMode") or "").strip()
    agent_role_key = str((agent or {}).get("roleKey") or "").strip()
    agent_prompt_template_id = str((agent or {}).get("promptTemplateId") or "").strip()
    dialogue_model_id = agent_dialogue_model_id(agent) if agent else ""
    agent_inbox_pending_count = _agent_inbox_pending_count_for_summary(agent)
    agent_primary_direct_session_id = str((agent or {}).get("directSessionId") or "").strip()
    agent_direct_session_mismatch = bool(
        agent_id
        and agent_primary_direct_session_id
        and agent_primary_direct_session_id != conversation["id"]
    )
    agent_status = _session_agent_status_payload(
        agent_id,
        agent,
        hydrate_agent=hydrate_agent,
        agent_lookup_checked=agent_lookup_checked,
        persisted_status_code=str(conversation.get("agentStatusCode") or "").strip(),
    )
    if not agent_status["agentMissing"] and bool(conversation.get("agentMissing")):
        agent_status = {
            "agentMissing": True,
            "agentStatusCode": str(conversation.get("agentStatusCode") or "missing_agent").strip() or "missing_agent",
            "agentStatusMessage": text_for(
                get_web_language(),
                zh="缺少有效 Agent：当前会话引用的 Agent 已不存在或不可用。",
                en="Missing valid Agent: this session references an Agent that no longer exists or is unavailable.",
            ),
        }
    agent_missing_id = str(conversation.get("agentMissingId") or "").strip()
    agent_direct_session_mismatch = bool(conversation.get("agentDirectSessionMismatch"))
    agent_primary_direct_session_id = str(conversation.get("agentPrimaryDirectSessionId") or "").strip()
    agent_display_name = str((agent or {}).get("displayName") or "").strip()
    if agent_status["agentMissing"] and not agent_display_name:
        agent_display_name = text_for(get_web_language(), zh="缺少有效 Agent", en="Missing Agent")
    raw_title = str(conversation["title"]).strip()
    session_kind = str(conversation.get("sessionKind") or "main").strip() or "main"
    task_title = str(conversation.get("taskTitle") or raw_title).strip() or raw_title
    display_agent_name = agent_display_name or raw_title
    display_title = task_title if session_kind == "child" else display_agent_name
    return {
        "id": conversation["id"],
        "title": display_title,
        "agentId": agent_id,
        "agentCode": agent_code,
        "agentDisplayName": display_agent_name,
        "agentAvatarImagePath": agent_avatar_image_path,
        "agentAvatarImageUrl": agent_avatar_image_url,
        "agentPrimaryMode": agent_primary_mode,
        "agentRoleKey": agent_role_key,
        "agentPromptTemplateId": agent_prompt_template_id,
        "agentInboxPendingCount": agent_inbox_pending_count,
        "agentMissingId": agent_missing_id,
        "agentDirectSessionMismatch": agent_direct_session_mismatch,
        "agentPrimaryDirectSessionId": agent_primary_direct_session_id,
        "dialogueModelId": dialogue_model_id,
        "workspacePath": str(conversation.get("workspacePath") or _session_workspace_relative_path(conversation["id"])),
        "agentWorkspacePath": agent_workspace_path,
        **agent_status,
        "status": status,
        "taskSummary": summary,
        "lastActive": updated_at,
        "updatedAt": updated_at,
        "currentPhase": status,
        "sessionKind": session_kind,
        "hiddenFromIndex": bool(conversation.get("hiddenFromIndex") or conversation.get("hidden_from_index")),
        "parentSessionId": str(conversation.get("parentSessionId") or "").strip(),
        "rootSessionId": str(conversation.get("rootSessionId") or conversation["id"]).strip() or conversation["id"],
        "childSessionIds": list(conversation.get("childSessionIds") or []),
        "activeChildSessionId": str(conversation.get("activeChildSessionId") or "").strip(),
        "childStatus": str(conversation.get("childStatus") or status).strip() or status,
        "taskTitle": task_title,
        "resultCard": _normalize_child_result_card(conversation.get("resultCard")),
    }


def _build_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    summary = _build_session_summary(conversation)
    return _build_session_detail_from_summary(conversation, summary, hydrate_agent=True)


def _build_lightweight_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    summary = _build_session_summary(conversation, hydrate_agent=False)
    return _build_session_detail_from_summary(conversation, summary, hydrate_agent=False)


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


def _build_session_detail_from_summary(
    conversation: dict[str, Any],
    summary: dict[str, Any],
    *,
    hydrate_agent: bool,
) -> dict[str, Any]:
    turn_control = _get_session_turn_control(conversation["id"])
    turn_snapshot = turn_control.snapshot() if turn_control is not None else {
        "stopRequested": False,
        "stopRequestedAt": "",
        "stopReason": "",
    }
    active_task = _normalize_session_active_task(
        conversation.get("active_task") or conversation.get("activeTask")
    )
    if not _is_task_tool_backed_active_task(active_task):
        active_task = None
    live_work_run = _active_chat_turn_work_run_for_session(conversation["id"])
    active_task = _active_task_with_live_work_run(active_task, live_work_run)
    changed_files = list(active_task.get("changed_files") or []) if active_task else []
    read_files = list(active_task.get("read_files") or []) if active_task else []
    preview_tabs = list(active_task.get("preview_tabs") or []) if active_task else []
    default_file_context = str(active_task.get("default_file_context") or "").strip() if active_task else ""
    active_preview_path = (
        str(active_task.get("active_preview_path") or "").strip() if active_task else ""
    ) or "agent"
    detail_messages = _messages_with_live_output(conversation["id"], conversation.get("messages") or [])
    context_usage = _build_session_context_usage(conversation, detail_messages)
    llm_usage = _session_last_llm_usage(conversation, detail_messages)
    cache_usage = _build_session_cache_usage(llm_usage, detail_messages)
    live_context_composition = _current_session_live_context_composition(conversation["id"])
    last_context_composition = live_context_composition or _normalize_session_context_composition(
        conversation.get("lastContextComposition") or conversation.get("last_context_composition")
    )
    last_cache_composition = (
        _build_session_cache_composition(
            str(live_context_composition.get("turnId") or "").strip(),
            llm_usage,
            context_composition=last_context_composition,
            average_cache=cache_usage,
        )
        if live_context_composition is not None
        else _session_last_cache_composition(
            conversation,
            llm_usage=llm_usage,
            context_composition=last_context_composition,
            average_cache=cache_usage,
        )
    )
    agent_available = _session_agent_is_available(summary)
    available_agent_id = summary.get("agentId") or "" if agent_available else ""
    available_agent = get_agent(available_agent_id) if available_agent_id and hydrate_agent else None
    detail = {
        **summary,
        "ledgerSeq": _session_ledger_sequence(conversation["id"]),
        "activeTask": _active_task_to_api(active_task),
        "defaultFileContext": default_file_context,
        "previewTabs": preview_tabs,
        "activePreviewPath": active_preview_path,
        "changedFiles": changed_files,
        "readFiles": read_files,
        "messages": detail_messages,
        "runtimeNotices": _visible_session_runtime_notices(conversation.get("runtimeNotices") or [], detail_messages),
        "contextUsage": context_usage,
        "cacheUsage": cache_usage,
        "llmUsage": llm_usage,
        "lastContextComposition": last_context_composition,
        "activeSkillContract": normalize_active_skill_contract(
            conversation.get("activeSkillContract") or conversation.get("active_skill_contract")
        ),
        "lastCacheComposition": last_cache_composition,
        "handoffContext": _normalize_child_handoff_context(conversation.get("handoffContext") or conversation.get("handoff_context")),
        "lastTurnError": _session_turn_error_to_api(conversation.get("lastTurnError")),
        "nextStateSignals": _recent_chat_next_state_signal_summaries(conversation["id"], limit=5) if hydrate_agent else [],
        "groupContextEvents": list_group_context_events_for_agent(available_agent_id, limit=8)
        if available_agent_id and hydrate_agent
        else [],
        "agentInboxMessages": list_agent_inbox_messages_for_agent(available_agent_id, limit=8, status="pending")
        if available_agent_id and hydrate_agent
        else [],
        "pendingToolGovernanceRequests": _pending_tool_governance_requests_for_session(available_agent_id)
        if available_agent_id and hydrate_agent
        else [],
        "toolPolicy": (available_agent or {}).get("toolPolicy") if available_agent_id else None,
        "memoryPolicy": (available_agent or {}).get("memoryPolicy") if available_agent_id else None,
        "stopRequested": bool(turn_snapshot["stopRequested"]) and not bool(turn_snapshot.get("releasedToUser")),
        "stopRequestedAt": ""
        if bool(turn_snapshot.get("releasedToUser"))
        else str(turn_snapshot["stopRequestedAt"] or "").strip(),
        "stopReason": ""
        if bool(turn_snapshot.get("releasedToUser"))
        else str(turn_snapshot["stopReason"] or "").strip(),
    }
    return detail


def _build_session_cache_usage(
    llm_usage: dict[str, Any] | None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    usage = _normalize_turn_llm_usage(llm_usage)
    usage_source = str((usage or {}).get("source") or "").strip()
    observed = usage is not None and usage_source == "provider_usage"
    last_input_tokens = _coerce_nonnegative_int((usage or {}).get("inputTokens") or 0) if observed else 0
    last_cached_input_tokens = min(
        _coerce_nonnegative_int((usage or {}).get("cachedInputTokens") or 0),
        last_input_tokens,
    ) if last_input_tokens else 0
    last_cache_creation_input_tokens = min(
        _coerce_nonnegative_int((usage or {}).get("cacheCreationInputTokens") or 0),
        last_input_tokens,
    ) if last_input_tokens else 0
    last_uncached_input_tokens = (
        _coerce_nonnegative_int((usage or {}).get("uncachedInputTokens") or 0)
        if observed
        else 0
    )
    if observed and last_input_tokens:
        last_uncached_input_tokens = max(0, last_input_tokens - last_cached_input_tokens)
    turn_input_tokens = last_input_tokens
    turn_cached_input_tokens = last_cached_input_tokens
    turn_cache_creation_input_tokens = last_cache_creation_input_tokens
    turn_uncached_input_tokens = last_uncached_input_tokens
    aggregate = _aggregate_session_provider_cache_usage(messages or [], fallback_usage=usage)
    aggregate_turn_count = _coerce_nonnegative_int(aggregate.get("turnCount") or 0)
    if aggregate_turn_count:
        total_input_tokens = _coerce_nonnegative_int(aggregate.get("inputTokens") or 0)
        total_cached_input_tokens = _coerce_nonnegative_int(aggregate.get("cachedInputTokens") or 0)
        total_cache_creation_input_tokens = _coerce_nonnegative_int(aggregate.get("cacheCreationInputTokens") or 0)
        total_uncached_input_tokens = _coerce_nonnegative_int(aggregate.get("uncachedInputTokens") or 0)
    else:
        total_input_tokens = last_input_tokens
        total_cached_input_tokens = last_cached_input_tokens
        total_cache_creation_input_tokens = last_cache_creation_input_tokens
        total_uncached_input_tokens = last_uncached_input_tokens
    if total_input_tokens and not total_uncached_input_tokens:
        total_uncached_input_tokens = max(0, total_input_tokens - total_cached_input_tokens)
    return {
        "lastInputTokens": last_input_tokens,
        "lastCachedInputTokens": last_cached_input_tokens,
        "lastCacheReadInputTokens": last_cached_input_tokens,
        "lastCacheCreationInputTokens": last_cache_creation_input_tokens,
        "lastUncachedInputTokens": last_uncached_input_tokens,
        "turnInputTokens": turn_input_tokens,
        "turnCachedInputTokens": turn_cached_input_tokens,
        "turnCacheReadInputTokens": turn_cached_input_tokens,
        "turnCacheCreationInputTokens": turn_cache_creation_input_tokens,
        "turnUncachedInputTokens": turn_uncached_input_tokens,
        "turnCacheHitRate": (turn_cached_input_tokens / turn_input_tokens) if turn_input_tokens > 0 else 0.0,
        "totalInputTokens": total_input_tokens,
        "totalCachedInputTokens": total_cached_input_tokens,
        "totalCacheReadInputTokens": total_cached_input_tokens,
        "totalCacheCreationInputTokens": total_cache_creation_input_tokens,
        "totalUncachedInputTokens": total_uncached_input_tokens,
        "totalCacheHitRate": (total_cached_input_tokens / total_input_tokens) if total_input_tokens > 0 else 0.0,
        "totalObservedTurnCount": aggregate_turn_count or (1 if observed else 0),
        "updatedAt": str((usage or {}).get("recordedAt") or "").strip(),
        "source": "provider_usage" if observed else "not_called" if usage_source == "not_called" else "missing",
    }


def _session_last_llm_usage(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = _normalize_turn_llm_usage(
        conversation.get("last_llm_usage")
        or conversation.get("lastLlmUsage")
    )
    if normalized is not None:
        return normalized
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


def _normalize_turn_llm_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    source = str(value.get("source") or "").strip() or "missing"
    if source in {"not_called", "not_called_preflight"}:
        source = "not_called"
    input_tokens = _coerce_nonnegative_int(value.get("input_tokens") or value.get("inputTokens") or 0)
    output_tokens = _coerce_nonnegative_int(value.get("output_tokens") or value.get("outputTokens") or 0)
    total_tokens = _coerce_nonnegative_int(value.get("total_tokens") or value.get("totalTokens") or 0)
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    cached_input_tokens = min(
        _coerce_nonnegative_int(value.get("cached_input_tokens") or value.get("cachedInputTokens") or 0),
        input_tokens,
    ) if input_tokens else 0
    cache_creation_input_tokens = min(
        _coerce_nonnegative_int(
            value.get("cache_creation_input_tokens")
            or value.get("cacheCreationInputTokens")
            or value.get("cache_write_input_tokens")
            or value.get("cacheWriteInputTokens")
            or 0
        ),
        input_tokens,
    ) if input_tokens else 0
    uncached_input_tokens = _coerce_nonnegative_int(
        value.get("uncached_input_tokens") or value.get("uncachedInputTokens") or 0
    )
    if input_tokens:
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)
    else:
        uncached_input_tokens = 0
    return {
        "source": source,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "cachedInputTokens": cached_input_tokens,
        "cacheReadInputTokens": cached_input_tokens,
        "cacheCreationInputTokens": cache_creation_input_tokens,
        "uncachedInputTokens": uncached_input_tokens,
        "cacheHitRate": (cached_input_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "provider": str(value.get("provider") or "").strip(),
        "model": str(value.get("model") or "").strip(),
        "promptCacheScope": str(value.get("prompt_cache_scope") or value.get("promptCacheScope") or "").strip(),
        "promptCachePartition": str(
            value.get("prompt_cache_partition") or value.get("promptCachePartition") or ""
        ).strip(),
        "llmModelId": str(value.get("llm_model_id") or value.get("llmModelId") or "").strip(),
        "recordedAt": str(value.get("recorded_at") or value.get("recordedAt") or "").strip(),
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


def _normalize_session_context_composition(value: Any) -> dict[str, Any] | None:
    normalized = normalize_context_manifest(value)
    if normalized is None or not isinstance(value, dict):
        return normalized
    raw_segments = [item for item in list(value.get("segments") or []) if isinstance(item, dict)]
    if not raw_segments:
        return normalized
    next_segments: list[dict[str, Any]] = []
    for index, item in enumerate(list(normalized.get("segments") or [])):
        segment = dict(item)
        raw = raw_segments[index] if index < len(raw_segments) else {}
        preview = _context_segment_content_preview(raw)
        if preview:
            segment["contentPreview"] = preview
        next_segments.append(segment)
    updated = dict(normalized)
    updated["segments"] = next_segments
    return updated


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


def _active_task_with_live_work_run(
    active_task: dict[str, Any] | None,
    live_work_run: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _is_task_tool_backed_active_task(active_task):
        return active_task
    if not isinstance(live_work_run, dict):
        return active_task
    status = str(live_work_run.get("status") or live_work_run.get("currentPhase") or "").strip().lower()
    if status not in {"queued", "running", "stopping", "paused"}:
        return active_task
    updated = dict(active_task or {})
    summary = str(live_work_run.get("summary") or "").strip()
    user_message = str(live_work_run.get("userMessage") or "").strip()
    now = str(live_work_run.get("updatedAt") or "").strip()
    updated["task_id"] = str(updated.get("task_id") or live_work_run.get("runId") or "").strip()
    updated["kind"] = str(updated.get("kind") or "chat_turn").strip()
    updated["status"] = status
    updated["latest_summary"] = summary or updated.get("latest_summary") or updated.get("latestSummary") or ""
    if user_message and not str(updated.get("goal") or "").strip():
        updated["goal"] = user_message
    if user_message and not str(updated.get("title") or "").strip():
        updated["title"] = trim_lines(user_message, max_lines=1)
    if user_message:
        updated["last_user_message"] = user_message
    if now:
        updated["updated_at"] = now
    metadata = dict(updated.get("metadata") or {}) if isinstance(updated.get("metadata"), dict) else {}
    metadata["liveWorkRunId"] = str(live_work_run.get("runId") or "").strip()
    metadata["liveWorkRunStatus"] = status
    updated["metadata"] = metadata
    return updated


def _normalize_session_cache_composition_segment(item: Any, *, default_status: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    key = str(item.get("key") or "").strip()
    if not key:
        return None
    estimated_raw = item.get("estimated")
    if isinstance(estimated_raw, str):
        estimated = estimated_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        estimated = bool(estimated_raw)
    return {
        "key": key,
        "label": str(item.get("label") or key).strip() or key,
        "tokens": _coerce_nonnegative_int(item.get("tokens") or 0),
        "status": str(item.get("status") or default_status).strip() or default_status,
        "source": str(item.get("source") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "cachePolicy": str(item.get("cachePolicy") or item.get("cache_policy") or "").strip(),
        "order": _coerce_nonnegative_int(item.get("order") or 0),
        "contentPreview": _context_segment_content_preview(item),
        "promptCategory": str(item.get("promptCategory") or item.get("prompt_category") or "").strip(),
        "segmentKind": str(item.get("segmentKind") or item.get("segment_kind") or "").strip(),
        "accuracy": str(item.get("accuracy") or "").strip(),
        "parentKey": str(item.get("parentKey") or item.get("parent_key") or "").strip(),
        "estimated": estimated,
        "observedStatus": str(item.get("observedStatus") or item.get("observed_status") or "").strip(),
        "observedCachedInputTokens": _coerce_nonnegative_int(
            item.get("observedCachedInputTokens") or item.get("observed_cached_input_tokens") or 0
        ),
        "observedMissedInputTokens": _coerce_nonnegative_int(
            item.get("observedMissedInputTokens") or item.get("observed_missed_input_tokens") or 0
        ),
        "computedOverestimatedInputTokens": _coerce_nonnegative_int(
            item.get("computedOverestimatedInputTokens") or item.get("computed_overestimated_input_tokens") or 0
        ),
        "providerExtraCachedInputTokens": _coerce_nonnegative_int(
            item.get("providerExtraCachedInputTokens") or item.get("provider_extra_cached_input_tokens") or 0
        ),
        "calibrationReason": str(item.get("calibrationReason") or item.get("calibration_reason") or "").strip(),
    }


def _normalize_session_cache_composition(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _coerce_nonnegative_int(value.get("inputTokens") or value.get("input_tokens") or 0)
    cached_tokens = _coerce_nonnegative_int(value.get("cachedInputTokens") or value.get("cached_input_tokens") or 0)
    if input_tokens:
        cached_tokens = min(cached_tokens, input_tokens)
    else:
        cached_tokens = 0
    cache_creation_tokens = _coerce_nonnegative_int(
        value.get("cacheCreationInputTokens")
        or value.get("cache_creation_input_tokens")
        or value.get("cacheWriteInputTokens")
        or value.get("cache_write_input_tokens")
        or 0
    )
    if input_tokens:
        cache_creation_tokens = min(cache_creation_tokens, input_tokens)
    else:
        cache_creation_tokens = 0
    uncached_tokens = _coerce_nonnegative_int(value.get("uncachedInputTokens") or value.get("uncached_input_tokens") or 0)
    if not uncached_tokens and input_tokens:
        uncached_tokens = max(0, input_tokens - cached_tokens)
    source = str(value.get("source") or "").strip() or "missing"
    if source in {"not_called", "not_called_preflight"}:
        source = "not_called"
    segments = []
    for item in list(value.get("segments") or []):
        segment = _normalize_session_cache_composition_segment(item, default_status="observed")
        if segment is not None:
            segments.append(segment)
    if not segments:
        if input_tokens:
            segments = [
                {"key": "cached", "label": "cached", "tokens": cached_tokens, "status": "hit"},
                {"key": "cache_write", "label": "cache write", "tokens": cache_creation_tokens, "status": "write"},
                {"key": "uncached", "label": "uncached", "tokens": uncached_tokens, "status": "miss"},
            ]
        elif source in {"missing", "not_called"}:
            segments = [{"key": "missing", "label": "missing", "tokens": 1, "status": "missing"}]
    computed_segments = []
    for item in list(value.get("computedSegments") or value.get("computed_segments") or []):
        segment = _normalize_session_cache_composition_segment(item, default_status="computed_unknown")
        if segment is not None:
            computed_segments.append(segment)
    calibrated_segments = []
    for item in list(value.get("calibratedSegments") or value.get("calibrated_segments") or []):
        segment = _normalize_session_cache_composition_segment(item, default_status="not_observed")
        if segment is not None:
            calibrated_segments.append(segment)
    computed_input_tokens = _coerce_nonnegative_int(
        value.get("computedInputTokens") or value.get("computed_input_tokens") or input_tokens
    )
    computed_cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("computedCachedInputTokens")
            or value.get("computed_cached_input_tokens")
            or 0
        ),
        computed_input_tokens,
    ) if computed_input_tokens else 0
    computed_uncached_tokens = _coerce_nonnegative_int(
        value.get("computedUncachedInputTokens")
        or value.get("computed_uncached_input_tokens")
        or 0
    )
    if computed_input_tokens and not computed_uncached_tokens:
        computed_uncached_tokens = max(0, computed_input_tokens - computed_cached_tokens)
    upper_bound_input_tokens = _coerce_nonnegative_int(
        value.get("upperBoundInputTokens")
        or value.get("upper_bound_input_tokens")
        or computed_input_tokens
    )
    upper_bound_cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("upperBoundCachedInputTokens")
            or value.get("upper_bound_cached_input_tokens")
            or computed_cached_tokens
        ),
        upper_bound_input_tokens,
    ) if upper_bound_input_tokens else 0
    upper_bound_uncached_tokens = _coerce_nonnegative_int(
        value.get("upperBoundUncachedInputTokens")
        or value.get("upper_bound_uncached_input_tokens")
        or 0
    )
    if upper_bound_input_tokens and not upper_bound_uncached_tokens:
        upper_bound_uncached_tokens = max(0, upper_bound_input_tokens - upper_bound_cached_tokens)
    average_input_tokens = _coerce_nonnegative_int(
        value.get("averageInputTokens") or value.get("average_input_tokens") or 0
    )
    average_cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("averageCachedInputTokens")
            or value.get("average_cached_input_tokens")
            or 0
        ),
        average_input_tokens,
    ) if average_input_tokens else 0
    average_turn_count = _coerce_nonnegative_int(
        value.get("averageObservedTurnCount")
        or value.get("average_observed_turn_count")
        or value.get("averageTurnCount")
        or value.get("average_turn_count")
        or 0
    )
    calibrated_cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("calibratedCachedInputTokens")
            or value.get("calibrated_cached_input_tokens")
            or cached_tokens
        ),
        input_tokens,
    ) if input_tokens else 0
    predicted_input_tokens = _coerce_nonnegative_int(
        value.get("predictedInputTokens")
        or value.get("predicted_input_tokens")
        or value.get("calibratedInputTokens")
        or value.get("calibrated_input_tokens")
        or input_tokens
    )
    predicted_cached_tokens = min(
        _coerce_nonnegative_int(
            value.get("predictedCachedInputTokens")
            or value.get("predicted_cached_input_tokens")
            or value.get("calibratedCachedInputTokens")
            or value.get("calibrated_cached_input_tokens")
            or calibrated_cached_tokens
        ),
        predicted_input_tokens,
    ) if predicted_input_tokens else 0
    predicted_uncached_tokens = _coerce_nonnegative_int(
        value.get("predictedUncachedInputTokens")
        or value.get("predicted_uncached_input_tokens")
        or 0
    )
    if predicted_input_tokens and not predicted_uncached_tokens:
        predicted_uncached_tokens = max(0, predicted_input_tokens - predicted_cached_tokens)
    computed_overestimated_tokens = _coerce_nonnegative_int(
        value.get("computedOverestimatedInputTokens")
        or value.get("computed_overestimated_input_tokens")
        or 0
    )
    provider_extra_cached_tokens = _coerce_nonnegative_int(
        value.get("providerExtraCachedInputTokens")
        or value.get("provider_extra_cached_input_tokens")
        or 0
    )
    return {
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
        "recordedAt": str(value.get("recordedAt") or value.get("recorded_at") or "").strip(),
        "source": source,
        "provider": str(value.get("provider") or "").strip(),
        "model": str(value.get("model") or "").strip(),
        "llmModelId": str(value.get("llmModelId") or value.get("llm_model_id") or "").strip(),
        "promptCacheScope": str(value.get("promptCacheScope") or value.get("prompt_cache_scope") or "").strip(),
        "promptCachePartition": str(value.get("promptCachePartition") or value.get("prompt_cache_partition") or "").strip(),
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "cacheReadInputTokens": cached_tokens,
        "cacheCreationInputTokens": cache_creation_tokens,
        "uncachedInputTokens": uncached_tokens,
        "cacheHitRate": (cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "segments": segments,
        "computedInputTokens": computed_input_tokens,
        "computedCachedInputTokens": computed_cached_tokens,
        "computedUncachedInputTokens": computed_uncached_tokens,
        "computedCacheHitRate": (computed_cached_tokens / computed_input_tokens) if computed_input_tokens > 0 else 0.0,
        "computedSegments": computed_segments,
        "upperBoundInputTokens": upper_bound_input_tokens,
        "upperBoundCachedInputTokens": upper_bound_cached_tokens,
        "upperBoundUncachedInputTokens": upper_bound_uncached_tokens,
        "upperBoundCacheHitRate": (upper_bound_cached_tokens / upper_bound_input_tokens) if upper_bound_input_tokens > 0 else 0.0,
        "calibratedInputTokens": input_tokens,
        "calibratedCachedInputTokens": calibrated_cached_tokens,
        "calibratedCacheHitRate": (calibrated_cached_tokens / input_tokens) if input_tokens > 0 else 0.0,
        "calibratedSegments": calibrated_segments,
        "predictedInputTokens": predicted_input_tokens,
        "predictedCachedInputTokens": predicted_cached_tokens,
        "predictedUncachedInputTokens": predicted_uncached_tokens,
        "predictedCacheHitRate": (predicted_cached_tokens / predicted_input_tokens) if predicted_input_tokens > 0 else 0.0,
        "computedOverestimatedInputTokens": computed_overestimated_tokens,
        "providerExtraCachedInputTokens": provider_extra_cached_tokens,
        "calibrationStatus": str(value.get("calibrationStatus") or value.get("calibration_status") or "").strip(),
        "calibrationReason": str(value.get("calibrationReason") or value.get("calibration_reason") or "").strip(),
        "predictionStatus": str(
            value.get("predictionStatus")
            or value.get("prediction_status")
            or value.get("calibrationStatus")
            or value.get("calibration_status")
            or ""
        ).strip(),
        "predictionReason": str(
            value.get("predictionReason")
            or value.get("prediction_reason")
            or value.get("calibrationReason")
            or value.get("calibration_reason")
            or ""
        ).strip(),
        "averageInputTokens": average_input_tokens,
        "averageCachedInputTokens": average_cached_tokens,
        "averageCacheHitRate": (average_cached_tokens / average_input_tokens) if average_input_tokens > 0 else 0.0,
        "averageObservedTurnCount": average_turn_count,
    }


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


def _build_computed_cache_segments(
    *,
    input_tokens: int,
    context_composition: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], int, int]:
    ordered_context_segments = _ordered_model_input_context_segments(context_composition)
    context_tokens = sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in ordered_context_segments)
    total_input_tokens = max(_coerce_nonnegative_int(input_tokens), context_tokens)
    if total_input_tokens <= 0:
        return (
            [
                {
                    "key": "computed_missing",
                    "label": "computed missing",
                    "tokens": 1,
                    "status": "computed_unknown",
                    "source": "no_provider_input",
                    "description": "No provider input tokens were available for computed cache diagnostics.",
                    "cachePolicy": "unknown",
                    "order": 0,
                    "contentPreview": "No provider input token payload was available for computed cache diagnostics.",
                }
            ],
            0,
            0,
        )
    segments: list[dict[str, Any]] = []
    computed_cached_tokens = 0
    prefix_open = True
    unexplained_tokens = max(0, total_input_tokens - context_tokens)
    if unexplained_tokens:
        segments.extend(_estimated_provider_prefix_cache_segments(unexplained_tokens))
        computed_cached_tokens += unexplained_tokens
    stable_policies = {"cacheable", "prefix_candidate", "assumed_stable_prefix"}
    volatile_policies = {"volatile", "never_cache", "dynamic"}
    for index, item in enumerate(ordered_context_segments, start=1 if unexplained_tokens else 0):
        tokens = _coerce_nonnegative_int(item.get("tokens") or 0)
        if tokens <= 0:
            continue
        cache_policy = str(item.get("cachePolicy") or item.get("cache_policy") or "").strip()
        key = str(item.get("key") or "").strip() or f"segment_{index}"
        if prefix_open and cache_policy in stable_policies:
            status = "computed_hit"
            computed_cached_tokens += tokens
        elif cache_policy in stable_policies:
            status = "computed_write"
        else:
            status = "computed_miss"
            if cache_policy in volatile_policies or cache_policy:
                prefix_open = False
        if cache_policy not in stable_policies:
            prefix_open = False
        segments.append(
            {
                "key": key,
                "label": str(item.get("label") or key).strip() or key,
                "tokens": tokens,
                "status": status,
                "source": str(item.get("source") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "cachePolicy": cache_policy,
                "order": index,
                "contentPreview": _context_segment_content_preview(item),
                "promptCategory": str(item.get("promptCategory") or item.get("prompt_category") or _context_prompt_category(key)).strip(),
                "segmentKind": "prompt_source",
                "accuracy": "manifest",
            }
        )
    computed_cached_tokens = min(computed_cached_tokens, total_input_tokens)
    return segments, computed_cached_tokens, max(0, total_input_tokens - computed_cached_tokens)


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


def _calibrate_session_cache_segments(
    *,
    source: str,
    provider: str,
    model: str,
    input_tokens: int,
    cached_tokens: int,
    cache_creation_tokens: int,
    computed_segments: list[dict[str, Any]],
    computed_cached_tokens: int,
) -> dict[str, Any]:
    normalized_input_tokens = _coerce_nonnegative_int(input_tokens)
    normalized_cached_tokens = min(_coerce_nonnegative_int(cached_tokens), normalized_input_tokens) if normalized_input_tokens else 0
    normalized_computed_cached_tokens = min(
        _coerce_nonnegative_int(computed_cached_tokens),
        normalized_input_tokens,
    ) if normalized_input_tokens else 0
    provider_observed = source == "provider_usage" and normalized_input_tokens > 0
    overestimated_tokens = max(0, normalized_computed_cached_tokens - normalized_cached_tokens) if provider_observed else 0
    provider_extra_cached_tokens = max(0, normalized_cached_tokens - normalized_computed_cached_tokens) if provider_observed else 0
    calibrated_segments: list[dict[str, Any]] = []
    for item in computed_segments:
        segment = dict(item)
        tokens = _coerce_nonnegative_int(segment.get("tokens") or 0)
        status = str(segment.get("status") or "").strip()
        if not provider_observed:
            observed_status = "not_observed"
            observed_cached = 0
            observed_missed = 0
        elif status == "computed_hit":
            observed_status = "observed_hit"
            observed_cached = tokens
            observed_missed = 0
        elif status == "computed_write":
            observed_status = "computed_write"
            observed_cached = 0
            observed_missed = tokens
        elif status == "computed_miss":
            observed_status = "computed_miss"
            observed_cached = 0
            observed_missed = tokens
        else:
            observed_status = "not_observed"
            observed_cached = 0
            observed_missed = 0
        segment["observedStatus"] = observed_status
        segment["observedCachedInputTokens"] = observed_cached
        segment["observedMissedInputTokens"] = observed_missed
        segment["computedOverestimatedInputTokens"] = 0
        segment["providerExtraCachedInputTokens"] = 0
        calibrated_segments.append(segment)
    remaining_overestimate = overestimated_tokens
    primary_indices = [
        index
        for index, item in enumerate(calibrated_segments)
        if item.get("status") == "computed_hit"
        and (
            str(item.get("source") or "") == "provider_input_remainder"
            or str(item.get("cachePolicy") or "") == "assumed_stable_prefix"
        )
    ]
    fallback_indices = [
        index
        for index, item in reversed(list(enumerate(calibrated_segments)))
        if item.get("status") == "computed_hit" and index not in set(primary_indices)
    ]
    for index in primary_indices + fallback_indices:
        if remaining_overestimate <= 0:
            break
        item = calibrated_segments[index]
        available = _coerce_nonnegative_int(item.get("observedCachedInputTokens") or 0)
        deducted = min(available, remaining_overestimate)
        if deducted <= 0:
            continue
        remaining_overestimate -= deducted
        observed_cached = max(0, available - deducted)
        observed_missed = _coerce_nonnegative_int(item.get("observedMissedInputTokens") or 0) + deducted
        item["observedCachedInputTokens"] = observed_cached
        item["observedMissedInputTokens"] = observed_missed
        item["computedOverestimatedInputTokens"] = _coerce_nonnegative_int(
            item.get("computedOverestimatedInputTokens") or 0
        ) + deducted
        item["observedStatus"] = "observed_miss" if observed_cached <= 0 else "observed_partial"
    if provider_extra_cached_tokens > 0:
        calibrated_segments.append(
            {
                "key": "provider_extra_hit",
                "label": "provider extra cached",
                "tokens": provider_extra_cached_tokens,
                "status": "provider_extra_hit",
                "source": "provider_usage",
                "description": "Provider reported cached input that the computed context manifest could not map to a cacheable segment.",
                "cachePolicy": "provider_observed",
                "order": len(calibrated_segments) + 1,
                "contentPreview": "Additional provider cache read outside the mapped session context manifest.",
                "observedStatus": "observed_hit",
                "observedCachedInputTokens": provider_extra_cached_tokens,
                "observedMissedInputTokens": 0,
                "computedOverestimatedInputTokens": 0,
                "providerExtraCachedInputTokens": provider_extra_cached_tokens,
                "calibrationReason": "Provider reported more cached input than computed cacheable segments.",
            }
        )
    status, reason = _provider_cache_calibration_reason(
        provider=provider,
        model=model,
        source=source,
        cache_creation_tokens=cache_creation_tokens,
        overestimated_tokens=overestimated_tokens,
        provider_extra_cached_tokens=provider_extra_cached_tokens,
    )
    if remaining_overestimate > 0:
        status = "unmapped_provider_gap"
        reason = f"{reason} {remaining_overestimate} computed cache tokens could not be mapped to a segment."
    return {
        "calibratedInputTokens": normalized_input_tokens,
        "calibratedCachedInputTokens": normalized_cached_tokens if provider_observed else 0,
        "calibratedCacheHitRate": (normalized_cached_tokens / normalized_input_tokens)
        if provider_observed and normalized_input_tokens > 0
        else 0.0,
        "calibratedSegments": calibrated_segments,
        "computedOverestimatedInputTokens": overestimated_tokens,
        "providerExtraCachedInputTokens": provider_extra_cached_tokens,
        "calibrationStatus": status,
        "calibrationReason": reason,
    }


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


def _enrich_session_cache_composition(
    composition: dict[str, Any] | None,
    *,
    context_composition: dict[str, Any] | None,
    average_cache: dict[str, Any] | None,
) -> dict[str, Any] | None:
    normalized = _normalize_session_cache_composition(composition)
    if normalized is None:
        return None
    input_tokens = _coerce_nonnegative_int(normalized.get("inputTokens") or 0)
    computed_segments, computed_cached, computed_uncached = _build_computed_cache_segments(
        input_tokens=input_tokens,
        context_composition=context_composition,
    )
    average = _cache_average_from_usage(average_cache)
    calibration = _calibrate_session_cache_segments(
        source=str(normalized.get("source") or ""),
        provider=str(normalized.get("provider") or ""),
        model=str(normalized.get("model") or normalized.get("llmModelId") or ""),
        input_tokens=input_tokens,
        cached_tokens=_coerce_nonnegative_int(normalized.get("cachedInputTokens") or 0),
        cache_creation_tokens=_coerce_nonnegative_int(normalized.get("cacheCreationInputTokens") or 0),
        computed_segments=computed_segments,
        computed_cached_tokens=computed_cached,
    )
    computed_input_total = max(
        input_tokens,
        sum(_coerce_nonnegative_int(item.get("tokens") or 0) for item in computed_segments),
    )
    enriched = {
        **normalized,
        "computedInputTokens": computed_input_total,
        "computedCachedInputTokens": computed_cached,
        "computedUncachedInputTokens": computed_uncached,
        "computedSegments": computed_segments,
        "upperBoundInputTokens": computed_input_total,
        "upperBoundCachedInputTokens": computed_cached,
        "upperBoundUncachedInputTokens": computed_uncached,
        **calibration,
        "predictedInputTokens": calibration["calibratedInputTokens"],
        "predictedCachedInputTokens": calibration["calibratedCachedInputTokens"],
        "predictedUncachedInputTokens": max(
            0,
            _coerce_nonnegative_int(calibration["calibratedInputTokens"])
            - _coerce_nonnegative_int(calibration["calibratedCachedInputTokens"]),
        ),
        "predictionStatus": calibration["calibrationStatus"],
        "predictionReason": calibration["calibrationReason"],
        "averageInputTokens": average["inputTokens"],
        "averageCachedInputTokens": average["cachedInputTokens"],
        "averageObservedTurnCount": average["observedTurnCount"],
    }
    return _normalize_session_cache_composition(enriched)


def _session_last_cache_composition(
    conversation: dict[str, Any],
    *,
    llm_usage: dict[str, Any] | None,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    existing = _normalize_session_cache_composition(
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


def _build_session_cache_composition(
    turn_id: str,
    llm_usage: dict[str, Any] | None,
    *,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = _normalize_turn_llm_usage(llm_usage)
    if usage is None or usage.get("source") != "provider_usage":
        return _enrich_session_cache_composition(
            {
                "turnId": turn_id,
                "recordedAt": _now_timestamp(),
                "source": "missing",
            },
            context_composition=context_composition,
            average_cache=average_cache,
        ) or {}
    input_tokens = _coerce_nonnegative_int(usage.get("inputTokens") or 0)
    cached_tokens = min(_coerce_nonnegative_int(usage.get("cachedInputTokens") or 0), input_tokens) if input_tokens else 0
    cache_creation_tokens = min(_coerce_nonnegative_int(usage.get("cacheCreationInputTokens") or 0), input_tokens) if input_tokens else 0
    uncached_tokens = max(0, input_tokens - cached_tokens)
    return _enrich_session_cache_composition(
        {
            "turnId": turn_id,
            "recordedAt": usage.get("recordedAt") or _now_timestamp(),
            "source": "provider_usage",
            "provider": usage.get("provider") or "",
            "model": usage.get("model") or "",
            "llmModelId": usage.get("llmModelId") or "",
            "promptCacheScope": usage.get("promptCacheScope") or "",
            "promptCachePartition": usage.get("promptCachePartition") or "",
            "inputTokens": input_tokens,
            "cachedInputTokens": cached_tokens,
            "cacheCreationInputTokens": cache_creation_tokens,
            "uncachedInputTokens": uncached_tokens,
            "segments": [
                {"key": "cached", "label": "cached", "tokens": cached_tokens, "status": "hit"},
                {"key": "cache_write", "label": "cache write", "tokens": cache_creation_tokens, "status": "write"},
                {"key": "uncached", "label": "uncached", "tokens": uncached_tokens, "status": "miss"},
            ],
        },
        context_composition=context_composition,
        average_cache=average_cache,
    ) or {}


def _build_session_context_usage(conversation: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    user_count = 0
    assistant_count = 0
    character_count = 0
    tool_call_count = 0
    for message in list(messages or []):
        role = str((message or {}).get("role") or "").strip().lower()
        if role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1
        content = str((message or {}).get("content") or "")
        thought = str((message or {}).get("thought") or "")
        character_count += len(content) + len(thought)
        tool_calls = (message or {}).get("toolCalls") or (message or {}).get("tool_calls") or []
        if isinstance(tool_calls, list):
            tool_call_count += len(tool_calls)
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                character_count += len(str(tool_call.get("name") or ""))
                character_count += len(str(tool_call.get("summary") or ""))
                character_count += len(str(tool_call.get("resultPreview") or tool_call.get("result_preview") or ""))
                character_count += len(str(tool_call.get("error") or ""))
    estimated_tokens = _estimate_session_context_tokens(character_count, tool_call_count)
    limit_payload = _session_context_limit_payload(conversation)
    limit = _coerce_nonnegative_int(limit_payload.get("limit") or 0)
    used = min(estimated_tokens, limit) if limit > 0 else estimated_tokens
    payload = {
        "used": used,
        "limit": limit,
        "limitSource": str(limit_payload.get("source") or "").strip(),
        "limitModelId": str(limit_payload.get("modelId") or "").strip(),
        "limitAgentId": str(limit_payload.get("agentId") or "").strip(),
        "estimatedTokens": estimated_tokens,
        "messageCount": len(list(messages or [])),
        "userMessageCount": user_count,
        "assistantMessageCount": assistant_count,
        "toolCallCount": tool_call_count,
        "source": "session_messages",
    }
    return payload


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


def _build_last_context_composition(
    *,
    conversation: dict[str, Any],
    turn_id: str,
    user_message: str,
    history_messages: list[dict[str, Any]],
    active_task: Any,
    runtime_context_block: str = "",
    dynamic_runtime_context_block: str = "",
    dynamic_runtime_context_included: bool = False,
    runtime_context_segments: list[dict[str, Any]] | None = None,
    guidance_context_block: str = "",
    guidance_context_included: bool = False,
    skill_runtime_context_block: str = "",
    skill_runtime_context_included: bool = False,
    active_skill_context_block: str = "",
    active_skill_context_included: bool = False,
    attachments: list[dict[str, Any]] | None = None,
    prompt_cache_partition: str = "",
) -> dict[str, Any]:
    segments = [
        _context_segment(
            "current_user",
            "current user",
            content=user_message,
            chars=len(str(user_message or "")),
            item_count=1 if str(user_message or "").strip() else 0,
            source="raw_user_message",
            description="Current user message passed as the turn prompt.",
            kind="current_user",
            lifecycle="turn",
            authority=60,
            volatility=100,
            relevance=100,
            placement="current_user",
            cache_policy="never_cache",
            retention="current_turn_only",
        ),
        _context_segment(
            "history",
            "history",
            chars=_message_list_chars(history_messages),
            item_count=len(list(history_messages or [])),
            source="seed_chat_history",
            description="Filtered prior chat messages seeded into the agent.",
            kind="history",
            lifecycle="session",
            authority=45,
            volatility=35,
            relevance=70,
            placement="history",
            cache_policy="prefix_candidate",
            retention="carryover_summary",
        ),
    ]
    active_task_chars = _active_task_context_chars(active_task)
    if active_task_chars:
        segments.append(
            _context_segment(
                "active_task",
                "task state",
                chars=active_task_chars,
                item_count=1,
                status="state_only",
                source="active_task",
                description="Session task state retained outside the LLM message list.",
                kind="session_contract",
                lifecycle="task",
                authority=75,
                volatility=60,
                relevance=85,
                placement="session_state",
                cache_policy="never_cache",
                retention="carryover_summary",
                included_in_model_input=False,
            )
        )
    agent_context_segments, agent_context_previews = _agent_context_manifest_segments(
        runtime_context_segments,
        dynamic_runtime_context_included=dynamic_runtime_context_included,
    )
    if agent_context_segments:
        segments.extend(agent_context_segments)
    elif runtime_context_block:
        segments.append(
            _context_segment(
                "agent_context",
                "agent context",
                content=runtime_context_block,
                chars=len(runtime_context_block),
                item_count=1,
                source="context_engine",
                description="Stable runtime context seeded into the agent system prefix.",
                kind="agent_static_context",
                lifecycle="stable",
                authority=80,
                volatility=15,
                relevance=70,
                placement="system_prefix",
                cache_policy="cacheable",
                retention="persist",
            )
        )
    if dynamic_runtime_context_block:
        dynamic_included = bool(dynamic_runtime_context_included)
        segments.append(
            _context_segment(
                "dynamic_runtime_context",
                "dynamic runtime context",
                content=dynamic_runtime_context_block,
                chars=len(dynamic_runtime_context_block),
                item_count=1,
                status="included" if dynamic_included else "omitted",
                source="context_engine",
                description=(
                    "Dynamic runtime context inserted into model input."
                    if dynamic_included
                    else "Dynamic runtime context was available but omitted from model input."
                ),
                kind="runtime_observation",
                lifecycle="turn",
                authority=50,
                volatility=90,
                relevance=55,
                placement="before_current_user" if dynamic_included else "omitted",
                cache_policy="never_cache",
                retention="current_turn_only",
                included_in_model_input=dynamic_included,
            )
        )
    if guidance_context_block:
        guidance_included = bool(guidance_context_included)
        segments.append(
            _context_segment(
                "guidance",
                "guidance",
                content=guidance_context_block,
                chars=len(guidance_context_block),
                item_count=1,
                status="included" if guidance_included else "omitted",
                source="operator_guidance",
                description=(
                    "Recent operator guidance inserted into model input."
                    if guidance_included
                    else "Recent operator guidance was available but omitted from model input."
                ),
                kind="operator_guidance",
                lifecycle="turn",
                authority=65,
                volatility=85,
                relevance=75,
                placement="before_current_user" if guidance_included else "omitted",
                cache_policy="volatile",
                retention="current_turn_only",
                included_in_model_input=guidance_included,
            )
        )
    if skill_runtime_context_block:
        skill_included = bool(skill_runtime_context_included)
        segments.append(
            _context_segment(
                "skill",
                "skill",
                content=skill_runtime_context_block,
                chars=len(skill_runtime_context_block),
                item_count=1,
                status="included" if skill_included else "omitted",
                source="skill_runtime_context",
                description=(
                    "Slash skill runtime context seeded into the agent before the current user message."
                    if skill_included
                    else "Slash skill runtime context was available but could not be seeded into model input."
                ),
                kind="slash_payload",
                lifecycle="turn",
                authority=70,
                volatility=95,
                relevance=90,
                placement="before_current_user" if skill_included else "omitted",
                cache_policy="volatile",
                retention="current_turn_only",
                included_in_model_input=skill_included,
            )
        )
    if active_skill_context_block:
        active_skill_included = bool(active_skill_context_included)
        segments.append(
            _context_segment(
                "active_skill",
                "active skill",
                content=active_skill_context_block,
                chars=len(active_skill_context_block),
                item_count=1,
                status="included" if active_skill_included else "omitted",
                source="active_skill_contract",
                description=(
                    "Compact active skill contract seeded into the agent before the current user message."
                    if active_skill_included
                    else "Active skill contract was available but could not be seeded into model input."
                ),
                kind="active_skill",
                lifecycle="task",
                authority=68,
                volatility=80,
                relevance=85,
                placement="before_current_user" if active_skill_included else "omitted",
                cache_policy="volatile",
                retention="carryover_summary",
                included_in_model_input=active_skill_included,
            )
        )
    normalized_attachments = _normalize_message_attachments(attachments)
    if normalized_attachments:
        segments.append(
            _context_segment(
                "attachments",
                "attachments",
                chars=sum(len(str(item.get("filename") or "")) + len(str(item.get("contentType") or "")) for item in normalized_attachments),
                item_count=len(normalized_attachments),
                source="user_attachments",
                description="User image attachments prepared for this turn.",
                kind="attachment",
                lifecycle="turn",
                authority=55,
                volatility=95,
                relevance=90,
                placement="current_user",
                cache_policy="never_cache",
                retention="current_turn_only",
            )
        )
    limit_payload = _session_context_limit_payload(conversation)
    normalized = build_context_manifest(
        turn_id=turn_id,
        recorded_at=_now_timestamp(),
        source="runtime_assembly",
        limit_tokens=_coerce_nonnegative_int(limit_payload.get("limit") or 0),
        limit_source=str(limit_payload.get("source") or "").strip(),
        limit_model_id=str(limit_payload.get("modelId") or "").strip(),
        limit_agent_id=str(limit_payload.get("agentId") or "").strip(),
        prompt_cache_partition=prompt_cache_partition,
        segments=segments,
    )
    content_previews = {
        "current_user": _compact_preview_text(user_message, max_lines=3, max_chars=240),
        "history": _message_list_content_preview(history_messages),
        "active_task": _active_task_content_preview(active_task),
        "agent_context": _compact_preview_text(runtime_context_block, max_lines=3, max_chars=240),
        "dynamic_runtime_context": _compact_preview_text(dynamic_runtime_context_block, max_lines=3, max_chars=240),
        "guidance": _compact_preview_text(guidance_context_block, max_lines=3, max_chars=240),
        "skill": _compact_preview_text(skill_runtime_context_block, max_lines=3, max_chars=240),
        "active_skill": _compact_preview_text(active_skill_context_block, max_lines=3, max_chars=240),
        "attachments": _compact_preview_text(
            ", ".join(str(item.get("filename") or item.get("contentType") or "") for item in normalized_attachments),
            max_lines=1,
            max_chars=240,
        ),
    }
    content_previews.update(agent_context_previews)
    normalized = _attach_context_segment_content_previews(
        normalized,
        {key: value for key, value in content_previews.items() if value},
    )
    return normalized or {
        "schemaVersion": 1,
        "turnId": str(turn_id or "").strip(),
        "recordedAt": _now_timestamp(),
        "source": "runtime_assembly",
        "totalChars": 0,
        "totalTokens": 0,
        "limitTokens": _coerce_nonnegative_int(limit_payload.get("limit") or 0),
        "limitSource": str(limit_payload.get("source") or "").strip(),
        "limitModelId": str(limit_payload.get("modelId") or "").strip(),
        "limitAgentId": str(limit_payload.get("agentId") or "").strip(),
        "segments": [],
        "ordering": [],
        "modelInputOrdering": [],
        "budgets": {
            "usedTokens": 0,
            "observedTokens": 0,
            "omittedTokens": 0,
            "observedChars": 0,
            "limitTokens": _coerce_nonnegative_int(limit_payload.get("limit") or 0),
            "droppedTokens": 0,
            "overLimit": False,
        },
        "cache": {
            "stablePrefixHash": "",
            "cacheableSegmentCount": 0,
            "volatileSegmentCount": 0,
            "firstVolatileSegmentIndex": -1,
            "promptCachePartitionHash": _short_hash(prompt_cache_partition),
            "missLikelyReason": "",
        },
    }


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


def _normalize_session_active_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    read_files = _normalize_project_paths(
        value.get("read_files") or value.get("readFiles") or [],
        existing_only=True,
    )
    changed_files = _normalize_project_paths(
        value.get("changed_files") or value.get("changedFiles") or [],
        existing_only=False,
    )
    preview_tabs = _merge_project_paths(
        _normalize_project_paths(
            value.get("preview_tabs") or value.get("previewTabs") or [],
            existing_only=True,
        ),
        _normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        _normalize_project_path(
            value.get("default_file_context") or value.get("defaultFileContext"),
            existing_only=False,
        )
        or (changed_files[-1] if changed_files else "")
        or (read_files[-1] if read_files else "")
    )
    active_preview_path = (
        _normalize_project_path(
            value.get("active_preview_path") or value.get("activePreviewPath"),
            existing_only=True,
        )
        or _normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
    )
    if active_preview_path and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]
    if not active_preview_path:
        active_preview_path = "agent"

    normalized = {
        "task_id": str(value.get("task_id") or value.get("taskId") or "").strip(),
        "kind": str(value.get("kind") or "coding").strip().lower() or "coding",
        "status": str(value.get("status") or "idle").strip().lower() or "idle",
        "title": trim_lines(_sanitize_message_content("assistant", value.get("title") or ""), max_lines=2),
        "goal": trim_lines(_sanitize_message_content("assistant", value.get("goal") or ""), max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": str(value.get("verification_status") or value.get("verificationStatus") or "").strip().lower(),
        "verification_summary": trim_lines(
            _sanitize_message_content(
                "assistant",
                value.get("verification_summary") or value.get("verificationSummary") or "",
            ),
            max_lines=4,
        ),
        "latest_summary": trim_lines(
            _sanitize_message_content(
                "assistant",
                value.get("latest_summary") or value.get("latestSummary") or "",
            ),
            max_lines=6,
        ),
        "next_action": trim_lines(
            _sanitize_message_content(
                "assistant",
                value.get("next_action") or value.get("nextAction") or "",
            ),
            max_lines=3,
        ),
        "last_user_message": trim_lines(
            value.get("last_user_message") or value.get("lastUserMessage") or "",
            max_lines=3,
        ),
        "turn_count": _coerce_nonnegative_int(value.get("turn_count") or value.get("turnCount") or 0),
        "resume_count": _coerce_nonnegative_int(value.get("resume_count") or value.get("resumeCount") or 0),
        "created_at": str(value.get("created_at") or value.get("createdAt") or "").strip(),
        "updated_at": str(value.get("updated_at") or value.get("updatedAt") or "").strip(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": dict(value.get("metadata") or {}) if isinstance(value.get("metadata"), dict) else {},
    }
    if not any(
        (
            normalized["read_files"],
            normalized["changed_files"],
            normalized["verification_status"],
            normalized["verification_summary"],
            normalized["next_action"],
            normalized["latest_summary"],
        )
    ):
        return None
    return normalized


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


def _is_agent_inbox_message_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    if _message_metadata_kind(item) == "agent_inbox_message":
        return True
    return _looks_like_agent_inbox_protocol_message(item.get("content"))


def _is_real_user_message_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    return not (_is_agent_inbox_message_entry(item) or _is_system_authored_user_message_entry(item))


def _latest_message_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        preview = _compact_preview_text(item.get("content") or "")
        if preview:
            return preview
    return ""


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


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


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


def _find_cli_agent_lifecycle_message(
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    lifecycle_key: str,
) -> dict[str, Any] | None:
    normalized_key = str(lifecycle_key or "").strip()
    if not normalized_key:
        return None
    normalized_messages = _normalize_messages(conversation_id, messages)
    for message in normalized_messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != "cli_agent_lifecycle":
            continue
        if str(metadata.get("lifecycleKey") or "").strip() == normalized_key:
            return message
    return None


def _find_cli_agent_task_result_message(
    messages: list[dict[str, Any]],
    *,
    result_key: str,
) -> dict[str, Any] | None:
    normalized_key = str(result_key or "").strip()
    if not normalized_key:
        return None
    for message in messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != "cli_agent_task_result":
            continue
        if str(metadata.get("resultKey") or "").strip() == normalized_key:
            return message
    return None


def _cli_agent_lifecycle_sidecar_path(session_id: str) -> Path:
    token = _safe_session_workspace_token(session_id)
    sessions_root = developer_sandbox.sandboxed_workspace_path(PROJECT_ROOT, "sessions").resolve()
    workspace_path = developer_sandbox.seeded_sandbox_workspace_path(PROJECT_ROOT, "sessions", token).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise SessionValidationError(f"Invalid session workspace path: {workspace_path}")
    return workspace_path / "logs" / "cli_agent_lifecycle.jsonl"


def _append_cli_agent_lifecycle_sidecar(session_id: str, message: dict[str, Any]) -> None:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    lifecycle_key = str(metadata.get("lifecycleKey") or "").strip()
    if not lifecycle_key:
        return
    if _find_cli_agent_lifecycle_sidecar_message(session_id, lifecycle_key=lifecycle_key) is not None:
        return
    try:
        path = _cli_agent_lifecycle_sidecar_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schemaVersion": 1,
            "timestamp": str(message.get("timestamp") or _now_timestamp()).strip(),
            "sessionId": str(session_id or "").strip(),
            "lifecycleKey": lifecycle_key,
            "event": str(metadata.get("event") or metadata.get("status") or "").strip(),
            "message": message,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as exc:
        _debug_logger.warning(
            f"cli agent lifecycle sidecar append skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _find_cli_agent_lifecycle_sidecar_message(
    session_id: str,
    *,
    lifecycle_key: str,
) -> dict[str, Any] | None:
    normalized_key = str(lifecycle_key or "").strip()
    if not normalized_key:
        return None
    for message in _load_cli_agent_lifecycle_sidecar_messages(session_id):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != "cli_agent_lifecycle":
            continue
        if str(metadata.get("lifecycleKey") or "").strip() == normalized_key:
            return message
    return None


def _load_cli_agent_lifecycle_sidecar_messages(session_id: str) -> list[dict[str, Any]]:
    try:
        path = _cli_agent_lifecycle_sidecar_path(session_id)
    except Exception:
        return []
    if not path.exists():
        return []
    result: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        text = str(line or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() != "cli_agent_lifecycle":
            continue
        result.append(dict(message))
    return result


def _merge_cli_agent_lifecycle_sidecar_messages(
    session_id: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(messages or [])
    seen_keys: set[str] = set()
    for message in merged:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        lifecycle_key = str(metadata.get("lifecycleKey") or "").strip()
        if str(metadata.get("kind") or "").strip() == "cli_agent_lifecycle" and lifecycle_key:
            seen_keys.add(lifecycle_key)
    additions: list[dict[str, Any]] = []
    for message in _load_cli_agent_lifecycle_sidecar_messages(session_id):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        lifecycle_key = str(metadata.get("lifecycleKey") or "").strip()
        if not lifecycle_key or lifecycle_key in seen_keys:
            continue
        seen_keys.add(lifecycle_key)
        additions.append(message)
    if not additions:
        return merged
    normalized = _normalize_messages(session_id, merged + additions)
    return sorted(normalized, key=lambda item: _timestamp_sort_key(str(item.get("timestamp") or "")))


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


def _child_session_created_card(*, child_id: str, title: str, auto_start: bool) -> str:
    status = "已自动开始" if auto_start else "已创建"
    return "\n".join(
        [
            f"子对话：{title}",
            f"状态：{status}",
            f"childSessionId: {child_id}",
        ]
    )


def _child_session_initial_prompt(user_request: str, handoff_context: dict[str, Any]) -> str:
    context = _normalize_child_handoff_context(handoff_context) or {}
    lines = [
        "[子对话启动上下文]",
        f"parentSessionId: {context.get('parentSessionId') or ''}",
        f"source: {context.get('source') or ''}",
        f"splitReason: {context.get('splitReason') or ''}",
    ]
    facts = list(context.get("inheritedFacts") or [])
    if facts:
        lines.append("inheritedFacts:")
        lines.extend(f"- {item}" for item in facts)
    constraints = list(context.get("constraints") or [])
    if constraints:
        lines.append("constraints:")
        lines.extend(f"- {item}" for item in constraints)
    files = list(context.get("relevantFiles") or [])
    if files:
        lines.append("relevantFiles:")
        lines.extend(f"- {item}" for item in files)
    logs = list(context.get("relevantLogs") or [])
    if logs:
        lines.append("relevantLogs:")
        lines.extend(f"- {item}" for item in logs)
    excluded = str(context.get("excludedContextSummary") or "").strip()
    if excluded:
        lines.append(f"excludedContextSummary: {excluded}")
    lines.extend(["", "[当前用户请求]", str(user_request or "").strip()])
    return "\n".join(lines).strip()


def _make_empty_conversation(session_id: str, *, title: str, timestamp: str) -> dict[str, Any]:
    return {
        "conversation_id": str(session_id or "").strip(),
        "title": str(title or "").strip() or DEFAULT_CHAT_CONVERSATION_TITLE,
        "workspace_path": _session_workspace_relative_path(session_id),
        "updated_at": str(timestamp or "").strip() or _now_timestamp(),
        "last_turn_status": "ready",
        "last_turn_error": None,
        "active_task": None,
        "messages": [],
    }


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
    try:
        profile = config.llm.get_profile(role=DEFAULT_SESSION_AGENT_PROFILE_ID)
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
        return str(model_id or "").strip()
    except Exception:
        return ""


def _session_agent_config_for_llm_bindings(agent_instance: dict[str, Any] | None) -> Any:
    return _session_agent_config_for_llm_slot(agent_instance, SESSION_LLM_SLOT_DIALOGUE)


def _resolve_session_agent_llm(agent_instance: dict[str, Any] | None, llm_slot: str) -> Any:
    normalized_slot = str(llm_slot or "").strip() or SESSION_LLM_SLOT_DIALOGUE
    try:
        return resolve_agent_llm(
            agent_instance,
            normalized_slot,
            config=get_config(),
            runtime_profile_id=DEFAULT_SESSION_AGENT_PROFILE_ID,
            fallback_to_dialogue=normalized_slot != SESSION_LLM_SLOT_DIALOGUE,
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
) -> str:
    """Build a short stable provider cache shard for the ordinary chat flow."""

    normalized_model = str(llm_model_id or model_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_slot = str(llm_slot or SESSION_LLM_SLOT_DIALOGUE).strip() or SESSION_LLM_SLOT_DIALOGUE
    normalized_template = str(prompt_template_id or "").strip()
    if normalized_agent_id:
        raw_parts = [
            SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC,
            normalized_agent_id,
            normalized_slot,
            normalized_model,
            normalized_template,
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
    return phase in {"running", "stopping"}


def _conversation_phase(conversation_id: str, conversation: dict[str, Any]) -> str:
    if _is_session_stop_requested(conversation_id):
        return "stopping"
    normalized = str(conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or "").strip().lower()
    if _is_session_running(conversation_id):
        if normalized == "queued":
            return "queued"
        return "running"
    if normalized in {
        "queued",
        "failed",
        "ready",
        "completed",
        "needs_continue",
        "paused_limit",
        "stopped_by_user",
        "failed_provider",
        "failed_runtime",
        "superseded",
    }:
        return normalized
    if conversation.get("messages"):
        return "ready"
    return "idle"


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


def _matches_attachment_intent_pattern(normalized: str, pattern: str) -> bool:
    if not pattern:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 _'-]*", pattern):
        return re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", normalized) is not None
    return pattern in normalized


def _contains_any_image_attachment_intent_pattern(normalized: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches_attachment_intent_pattern(normalized, pattern) for pattern in patterns)


def _has_explicit_image_generation_or_edit_intent(normalized: str) -> bool:
    return _contains_any_image_attachment_intent_pattern(normalized, _IMAGE_ATTACHMENT_IMAGE2_EXPLICIT_PATTERNS)


def _has_vision_analysis_intent(normalized: str) -> bool:
    return _contains_any_image_attachment_intent_pattern(normalized, _IMAGE_ATTACHMENT_VISION_PATTERNS)


def _classify_image_attachment_intent(message: str, *, default_nonempty_to_vision: bool = False) -> str:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return "clarify"
    if _has_explicit_image_generation_or_edit_intent(normalized):
        return "image2_edit"
    if _has_vision_analysis_intent(normalized):
        return "vision_analysis"
    return "vision_analysis" if default_nonempty_to_vision else "clarify"


def _resolve_image_attachment_turn_route(
    message: str,
    *,
    agent_instance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent = _classify_image_attachment_intent(message, default_nonempty_to_vision=True)
    route_llm_slot = (
        SESSION_LLM_SLOT_VISION
        if intent in {"image2_edit", "vision_analysis"}
        else SESSION_LLM_SLOT_DIALOGUE
    )
    supports_image_input = _session_agent_supports_image_input(agent_instance, slot=route_llm_slot)
    model_id = _session_agent_llm_slot_model_id(agent_instance, route_llm_slot)
    model_name = _session_agent_llm_model_name(agent_instance, slot=route_llm_slot)
    if supports_image_input is None:
        supports_image_input = False
    if intent in {"image2_edit", "vision_analysis"} and supports_image_input is True:
        route = "vision"
    elif intent in {"image2_edit", "vision_analysis"}:
        route = "block_vision"
    else:
        route = "clarify"
    return {
        "intent": intent,
        "route": route,
        "supports_image_input": supports_image_input,
        "model_name": model_name,
        "model_id": model_id,
        "llm_slot": route_llm_slot if model_id else "",
    }


def _session_agent_supports_image_input(agent_instance: dict[str, Any] | None, *, slot: str = SESSION_LLM_SLOT_DIALOGUE) -> bool | None:
    model_id = _session_agent_llm_slot_model_id(agent_instance, slot)
    if not model_id:
        return None
    try:
        llm_config = get_config().llm
        entry = llm_config.model_library.get(model_id)
    except Exception:
        return None
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


def _image_attachment_clarification_message(lang: str) -> str:
    return text_for(
        lang,
        zh="我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
        en="I received your image. Do you want me to analyze it, or generate/edit an image based on it? Please add your goal.",
    )


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
        zh=f"当前 Agent 使用的对话模型 `{model_label}` 未确认支持图像输入，所以我没有把图片发送给模型。请在 Agent 管理中切换到支持图像输入的对话模型；需要生成/调整图片时，由对话模型理解上下文后再按工具协议调用 image2 工具。",
        en=f"The current Agent dialogue model `{model_label}` is not confirmed to support image input, so I did not send the image to the model. Switch this Agent to a vision-capable dialogue model; image generation/editing should be invoked by the dialogue model through the image2 tool protocol after it understands the context.",
    )


def _finish_image_attachment_routed_turn(
    session_id: str,
    turn_id: str,
    result: dict[str, Any],
    *,
    route: str,
    intent: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    leases: list[str] | None,
    raw_user_message: str,
    outcome: str = "completed",
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    _record_image_attachment_router_event(
        session_id,
        turn_id=turn_id,
        route=route,
        intent=intent,
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


def _record_image_attachment_router_event(
    session_id: str,
    *,
    turn_id: str,
    route: str,
    intent: str,
    outcome: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "image_attachment_router",
            "conversation.image_attachment_router.routed",
            level=level,
            outcome=outcome,
            message="Conversation image attachment routed before LLM execution.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "route": str(route or "").strip(),
                "intent": str(intent or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "attachmentCount": len(_normalize_message_attachments(attachments or [])),
                "attachments": _safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-image-router.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "turn_id": str(turn_id or "").strip(),
                "route": str(route or "").strip(),
                "intent": str(intent or "").strip(),
                "agent_id": str(agent_id or "").strip(),
                "attachment_count": len(_normalize_message_attachments(attachments or [])),
                "attachments": _safe_attachment_log_summary(attachments or []),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene image attachment router log skipped: {type(exc).__name__}: {exc}",
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
    _WORK_RUN_STORE.persist_snapshot("chat_turn", payload, active_run_id=active_run_id)


def _replacement_active_chat_turn_id(*, exclude_turn_id: str = "") -> str:
    excluded = str(exclude_turn_id or "").strip()
    with _RUNNING_SESSIONS_LOCK:
        for turn_id in _SESSION_ACTIVE_TURN_IDS.values():
            normalized = str(turn_id or "").strip()
            if normalized and normalized != excluded:
                return normalized
    return ""


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


def _session_scheduler_agent_key(context: dict[str, Any]) -> str:
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    if agent_id:
        return f"agent:{agent_id}"
    session_id = str(context.get("session_id") or "").strip()
    return f"session:{session_id or 'unknown'}"


def _session_scheduler_session_key(context: dict[str, Any]) -> str:
    session_id = str(context.get("session_id") or context.get("sessionId") or "").strip()
    if session_id:
        return f"session:{session_id}"
    turn_id = str(context.get("turn_id") or context.get("turnId") or "").strip()
    return f"turn:{turn_id or 'unknown'}"


def _record_scheduler_event_adapter(
    context: dict[str, Any],
    phase: str,
    outcome: str,
    fields: dict[str, Any] | None,
) -> None:
    _record_session_scheduler_event(context, phase, outcome=outcome, fields=fields)


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


@contextmanager
def reserve_agent_execution_slot(
    *,
    agent_id: str,
    run_id: str,
    session_id: str = "",
    owner: str = "external",
    wait_timeout_seconds: float | None = None,
):
    """Reserve the per-agent execution slot for non-session work such as group chat speakers."""

    with _SESSION_TURN_SCHEDULER.reserve_external(
        agent_id=agent_id,
        run_id=run_id,
        session_id=session_id,
        owner=owner,
        wait_timeout_seconds=wait_timeout_seconds,
        release=_release_scheduled_session_turn,
    ):
        yield


def _scheduler_context_is_external(context: dict[str, Any]) -> bool:
    return _SESSION_TURN_SCHEDULER.is_external(context)


def _cancel_queued_scheduler_context(agent_key: str, turn_id: str) -> bool:
    return _SESSION_TURN_SCHEDULER.cancel_queued_context(agent_key, turn_id)


def cancel_agent_execution_reservation(run_id: str) -> bool:
    """Cancel queued external work that is waiting for an agent execution slot."""

    return _SESSION_TURN_SCHEDULER.cancel_external_reservation(run_id)


def _schedule_session_turn(context: dict[str, Any]) -> None:
    _SESSION_TURN_SCHEDULER.schedule(
        context,
        submit=_submit_scheduled_session_turn,
        release=_release_scheduled_session_turn,
    )


def _submit_scheduled_session_turn(context: dict[str, Any]) -> None:
    context["_executor_submitted_at_monotonic"] = _perf_counter()
    _SESSION_EXECUTOR.submit(_execute_scheduled_session_turn, context)


def _execute_scheduled_session_turn(context: dict[str, Any]) -> None:
    executor_started_at = _perf_counter()
    context["_executor_started_at_monotonic"] = executor_started_at
    try:
        _run_session_turn(context)
    finally:
        _release_scheduled_session_turn(context)


def _release_scheduled_session_turn(context: dict[str, Any]) -> None:
    released = _SESSION_TURN_SCHEDULER.release(context)
    if released is None:
        return

    for dropped in released.dropped_contexts:
        _record_session_scheduler_event(dropped, "dropped_stale", outcome="skipped")

    next_context = released.context
    if next_context is None:
        return
    if released.external:
        _record_session_scheduler_event(next_context, "external_dequeued", outcome="running")
        return

    contexts_to_submit = [next_context, *list(released.additional_contexts or [])]
    for runnable_context in contexts_to_submit:
        _submit_released_session_turn(runnable_context)


def _submit_released_session_turn(next_context: dict[str, Any]) -> None:
    try:
        _submit_scheduled_session_turn(next_context)
    except Exception as exc:
        _record_session_turn_lifecycle_event(
            str(next_context.get("session_id") or "").strip(),
            "scheduler_submit_failed",
            turn_id=str(next_context.get("turn_id") or "").strip(),
            level="error",
            outcome="failed",
            fields={
                "exceptionType": type(exc).__name__,
                "errorPreview": trim_lines(str(exc), max_lines=2),
                "agentId": str(next_context.get("agent_id") or "").strip(),
                **_scheduler_log_fields(next_context),
            },
        )
        _persist_session_turn_failure(str(next_context.get("session_id") or "").strip(), next_context, exc)
        _set_session_running(
            str(next_context.get("session_id") or "").strip(),
            False,
            turn_id=str(next_context.get("turn_id") or "").strip(),
        )
        _clear_session_turn_control(
            str(next_context.get("session_id") or "").strip(),
            turn_id=str(next_context.get("turn_id") or "").strip(),
        )
        _publish_session_detail_snapshot(str(next_context.get("session_id") or "").strip())
        _release_scheduled_session_turn(next_context)


def _cancel_queued_session_turn(session_id: str, turn_id: str) -> bool:
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    removed = _SESSION_TURN_SCHEDULER.cancel_session_turn(normalized_session_id, normalized_turn_id)
    if removed:
        _record_session_turn_lifecycle_event(
            normalized_session_id,
            "scheduler_cancelled_queued",
            turn_id=normalized_turn_id,
            outcome="cancelled",
            fields={"reason": "stop_requested_before_worker_start"},
        )
    return removed


def _mark_session_turn_queued(context: dict[str, Any], *, queue_position: int) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if not session_id or not _is_session_turn_current(session_id, turn_id):
        return
    context["_scheduler_queued_at_monotonic"] = _perf_counter()
    now = _now_timestamp()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is not None and _is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "queued"
            conversation["updated_at"] = now
            payload["updated_at"] = now
            save_chat_state(PROJECT_ROOT, payload)
    _set_session_turn_progress_live_output(session_id, "queued", turn_id=turn_id)
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="queued",
        agent_id=str(context.get("agent_id") or "").strip(),
        user_message=str(context.get("raw_user_message") or context.get("user_message") or "").strip(),
        updated_at=now,
    )
    _record_session_scheduler_event(
        context,
        "queued",
        outcome="queued",
        fields={
            "queuePosition": max(1, int(queue_position or 1)),
            **_scheduler_log_fields(context),
        },
    )
    _publish_session_detail_snapshot(session_id)


def _mark_session_turn_dequeued(context: dict[str, Any]) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if not session_id or not _is_session_turn_current(session_id, turn_id):
        return
    dequeued_at = _perf_counter()
    context["_scheduler_started_at_monotonic"] = dequeued_at
    now = _now_timestamp()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is not None and _is_session_turn_current(session_id, turn_id):
            conversation["last_turn_status"] = "running"
            conversation["updated_at"] = now
            payload["updated_at"] = now
            save_chat_state(PROJECT_ROOT, payload)
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status="running",
        agent_id=str(context.get("agent_id") or "").strip(),
        user_message=str(context.get("raw_user_message") or context.get("user_message") or "").strip(),
        updated_at=now,
    )
    _record_session_scheduler_event(
        context,
        "dequeued",
        outcome="running",
        fields={
            "queueWaitMs": _elapsed_ms_between(context.get("_scheduler_queued_at_monotonic"), dequeued_at),
            "scheduledToDequeueMs": _elapsed_ms_between(context.get("_scheduler_scheduled_at_monotonic"), dequeued_at),
            **_scheduler_log_fields(context),
        },
    )
    _publish_session_detail_snapshot(session_id)


def _scheduler_log_fields(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schedulerSessionKey": str(context.get("_scheduler_session_key") or _session_scheduler_session_key(context)).strip(),
        "queueReason": str(context.get("_scheduler_queue_reason") or "").strip(),
        "agentActiveCount": _coerce_nonnegative_int(context.get("_scheduler_agent_active_count")),
        "agentMaxActive": _coerce_nonnegative_int(
            context.get("_scheduler_agent_max_active") or _SESSION_AGENT_MAX_ACTIVE_TURNS
        ),
    }


def _record_session_scheduler_event(
    context: dict[str, Any],
    phase: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    agent_key = str(context.get("_scheduler_agent_key") or _session_scheduler_agent_key(context)).strip()
    _record_session_turn_lifecycle_event(
        session_id,
        f"scheduler_{phase}",
        turn_id=turn_id,
        outcome=outcome,
        fields={
            "agentId": str(context.get("agent_id") or context.get("agentId") or "").strip(),
            "schedulerAgentKey": agent_key,
            **_scheduler_log_fields(context),
            **(fields or {}),
        },
    )


def _run_session_turn(context: dict[str, Any]) -> None:
    prepare_started_at = _perf_counter()
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if turn_id and not _is_session_turn_current(session_id, turn_id):
        _record_session_turn_lifecycle_event(
            session_id,
            "skipped_stale",
            turn_id=turn_id,
            outcome="skipped",
            fields={
                "reason": "turn_id_not_current",
            },
        )
        return
    turn_control = context.get("turn_control")
    if not isinstance(turn_control, SessionTurnControl):
        turn_control = _get_session_turn_control(session_id)
    turn_capture = SessionTurnCapture(session_id=session_id, turn_id=turn_id)
    mental_model_enabled = _normalize_optional_bool(context.get("mental_model_enabled"))
    llm_slot = str(context.get("llm_slot") or SESSION_LLM_SLOT_DIALOGUE).strip() or SESSION_LLM_SLOT_DIALOGUE
    prepare_timings: dict[str, Any] = {}
    stage_started_at = _perf_counter()
    session_workspace = _ensure_session_workspace(session_id)
    prepare_timings["sessionWorkspaceMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    _sync_agent_directory_project_root()
    prepare_timings["agentDirectorySyncMs"] = _elapsed_ms(stage_started_at)
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    stage_started_at = _perf_counter()
    agent_instance = get_agent(agent_id, include_archived=False) if agent_id else None
    historical_agent = None if agent_instance else (get_agent(agent_id, include_archived=True) if agent_id else None)
    prepare_timings["agentLookupMs"] = _elapsed_ms(stage_started_at)
    stage_started_at = _perf_counter()
    turn_attachments = _normalize_message_attachments(context.get("attachments") or [])
    lightweight_chat_payload, lightweight_chat_payload_reason = _lightweight_chat_payload_decision(
        context,
        attachments=turn_attachments,
    )
    prepare_timings["lightweightChatDecisionMs"] = _elapsed_ms(stage_started_at)
    prepare_timings["lightweightChatPayload"] = lightweight_chat_payload
    prepare_timings["lightweightChatPayloadReason"] = lightweight_chat_payload_reason
    stage_started_at = _perf_counter()
    agent_context_packet = (
        build_agent_context(agent_id, session_id=session_id, run_id=turn_id)
        if agent_id
        else None
    )
    prepare_timings["agentContextBuildMs"] = _elapsed_ms(stage_started_at)
    prepare_timings["agentContextBuildSkipped"] = bool(agent_id and agent_context_packet is None)
    agent_context_timings = (
        dict(getattr(agent_context_packet, "timings", {}) or {})
        if agent_context_packet is not None
        else {}
    )
    for timing_key, timing_value in agent_context_timings.items():
        normalized_key = str(timing_key or "").strip()
        if not normalized_key:
            continue
        prepare_timings[f"agentContext.{normalized_key}"] = timing_value
    agent_workspace = str((agent_instance or {}).get("workspacePath") or "").strip()
    memory_policy = (
        agent_context_packet.memory_policy
        if agent_context_packet is not None
        else (resolve_memory_policy_for_agent(agent_id) if agent_id else {})
    )
    memory_root = str(memory_policy.get("privateMemoryRoot") or "").strip()
    agent_workspace_path = (
        agent_directory_service._ensure_agent_workspace(str((agent_instance or {}).get("workspacePath") or "")).resolve()
        if agent_instance and str((agent_instance or {}).get("workspacePath") or "").strip()
        else session_workspace
    )
    stage_started_at = _perf_counter()
    workspace_decision = (
        evaluate_agent_workspace_write(agent_id, agent_workspace_path, purpose="chat_turn_tool_workspace")
        if agent_id
        else None
    )
    prepare_timings["workspacePolicyMs"] = _elapsed_ms(stage_started_at)
    tool_workspace = agent_workspace_path if not workspace_decision or workspace_decision.allowed else session_workspace
    resolved_agent_llm = None
    if agent_instance:
        stage_started_at = _perf_counter()
        try:
            resolved_agent_llm = _resolve_session_agent_llm(agent_instance, llm_slot)
        except SessionValidationError as exc:
            visible = str(exc)
            missing_model_id = _extract_missing_agent_llm_model_id(visible)
            turn_error = _make_local_runtime_turn_error(
                visible,
                lang=get_web_language(),
                error_type="agent_llm_resolution_failed",
                reason_code="agent_llm_model_missing" if missing_model_id else "agent_llm_resolution_failed",
                reason_summary=text_for(
                    get_web_language(),
                    zh="当前 Agent 绑定的对话模型不在模型库中",
                    en="The current Agent dialogue model is not present in the model library",
                )
                if missing_model_id
                else text_for(
                    get_web_language(),
                    zh="当前 Agent 的模型槽位无法解析",
                    en="The current Agent model slot could not be resolved",
                ),
                reason_detail=visible,
                turn_id=turn_id,
                model=missing_model_id,
                extra={"llmSlot": llm_slot, "agentId": agent_id},
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "agent_llm_resolve_failed",
                turn_id=turn_id,
                outcome="failed",
                fields={
                    "agentId": agent_id,
                    "llmSlot": llm_slot,
                    "errorType": type(exc).__name__,
                    "error": visible,
                },
            )
            _persist_session_turn_runtime_error(
                session_id,
                turn_error,
                raw_error=visible,
                turn_id=turn_id,
                status="failed_runtime",
                work_run_summary=text_for(
                    get_web_language(),
                    zh="本轮在本地模型槽位解析阶段失败，未调用 provider。",
                    en="This turn failed while resolving the local model slot before any provider call.",
                ),
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "worker_finished",
                turn_id=turn_id,
                outcome="failed_runtime",
                fields={
                    "wasCurrentTurn": _is_session_turn_current(session_id, turn_id),
                    "reason": "agent_llm_resolution_failed",
                },
            )
            _set_session_running(session_id, False, turn_id=turn_id)
            _clear_session_turn_control(session_id, turn_id=turn_id)
            _publish_session_detail_snapshot(session_id)
            return
        prepare_timings["agentLlmResolveMs"] = _elapsed_ms(stage_started_at)
    prepare_timings["totalPrepareMs"] = _elapsed_ms(prepare_started_at)
    llm_model_id_for_turn = str(getattr(resolved_agent_llm, "model_id", "") or "") or _session_agent_llm_slot_model_id(
        agent_instance or historical_agent,
        llm_slot,
    )
    llm_runtime_diagnostics = (
        resolved_agent_llm.log_fields()
        if resolved_agent_llm is not None
        else {"llmModelId": llm_model_id_for_turn}
    )
    prompt_cache_partition = _session_prompt_cache_partition(
        session_id=session_id,
        agent_id=agent_id,
        llm_slot=llm_slot,
        model_id=llm_model_id_for_turn,
        prompt_template_id=str((agent_instance or {}).get("promptTemplateId") or "").strip(),
    )
    prompt_cache_scope = _session_prompt_cache_scope(agent_id=agent_id)
    _record_session_turn_lifecycle_event(
        session_id,
        "worker_started",
        turn_id=turn_id,
        outcome="running",
        fields={
            "workspacePath": _session_workspace_relative_path(session_id),
            "hasTurnControl": isinstance(turn_control, SessionTurnControl),
            "mentalModelEnabled": mental_model_enabled,
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
            "agentId": agent_id,
            "agentWorkspacePath": agent_workspace,
            "agentMemoryRoot": memory_root,
            "toolWorkspacePath": str(tool_workspace),
            "toolWorkspaceScope": str(getattr(workspace_decision, "scope", "") or ""),
            **_session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            "executorWaitMs": _elapsed_ms_between(context.get("_executor_submitted_at_monotonic"), prepare_started_at),
            "schedulerToWorkerStartedMs": _elapsed_ms_between(
                context.get("_scheduler_started_at_monotonic") or context.get("_scheduler_scheduled_at_monotonic"),
                _perf_counter(),
            ),
            "hasAgentContextPacket": agent_context_packet is not None,
            "lightweightChatPayload": lightweight_chat_payload,
            "lightweightChatPayloadReason": lightweight_chat_payload_reason,
            "disableTools": lightweight_chat_payload,
            **prepare_timings,
        },
    )
    _record_session_turn_lifecycle_event(
        session_id,
        "agent_runtime_resolved",
        turn_id=turn_id,
        outcome="resolved" if agent_instance else "fallback",
        fields={
            "mode": "chat",
            "agentId": agent_id,
            "agentCode": str((agent_instance or {}).get("agentCode") or "").strip(),
            "dialogueModelId": agent_dialogue_model_id(agent_instance),
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
            "promptTemplateId": str((agent_instance or {}).get("promptTemplateId") or "").strip(),
            "roleKey": str((agent_instance or {}).get("roleKey") or "").strip(),
            "source": "AgentLlmBindings" if agent_instance else "missing_agent",
            **_session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            **(resolved_agent_llm.log_fields() if resolved_agent_llm is not None else {}),
        },
    )
    _record_session_turn_lifecycle_event(
        session_id,
        "prompt_cache_partition_bound",
        turn_id=turn_id,
        outcome="bound",
        fields={
            "scope": prompt_cache_scope,
            **_session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
            "agentId": agent_id,
            "llmSlot": llm_slot,
            "llmModelId": llm_model_id_for_turn,
        },
    )
    _record_session_execution_registry_event(
        session_id,
        turn_id,
        "main_agent_loop",
        "running",
        details={"workspacePath": _session_workspace_relative_path(session_id)},
    )
    _record_session_execution_registry_event(
        session_id,
        turn_id,
        "mental_model",
        "enabled" if mental_model_enabled else "disabled",
        details={"perTurnOption": mental_model_enabled},
    )
    _record_session_turn_trace_event(
        session_id,
        turn_id,
        "state",
        {"phase": "worker_started", "workspacePath": _session_workspace_relative_path(session_id)},
        status="running",
        summary="Chat turn worker started.",
    )
    _set_session_turn_progress_live_output(session_id, "agent_prepare", turn_id=turn_id)
    try:
        if agent_id and not agent_instance:
            status = str((historical_agent or {}).get("status") or "").strip().lower()
            reason = "archived_agent" if status == "archived" else "missing_agent"
            visible = _session_agent_unavailable_message(reason, lang=get_web_language())
            _record_session_agent_unavailable_event(
                session_id,
                agent_id=agent_id,
                reason=reason,
                agent_status=status,
            )
            _persist_session_turn_result(
                session_id,
                {
                    "status": "failed_runtime",
                    "summary": visible,
                    "raw_output": visible,
                    "error": visible,
                    "outcome": "blocked",
                    "metadata": {"reason": reason},
                },
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace,
                active_task_hint=context.get("active_task"),
                user_message_source=str(context.get("user_message_source") or "").strip(),
                turn_id=turn_id,
            )
            return
        with (
            active_agent_runtime(agent_id, session_id=session_id, turn_id=turn_id),
            mental_model_enabled_override(mental_model_enabled),
            _session_tool_workspace_override(tool_workspace, memory_workspace=agent_workspace_path if agent_instance else tool_workspace),
        ):
            initial_stop_reason = _get_turn_control_stop_reason(turn_control)
            if initial_stop_reason:
                _record_session_turn_lifecycle_event(
                    session_id,
                    "stop_observed",
                    turn_id=turn_id,
                    outcome="stopped",
                    fields={
                        "stage": "initial",
                        "stopReason": trim_lines(initial_stop_reason, max_lines=2),
                    },
                )
                _persist_session_turn_result(
                    session_id,
                    _build_stopped_turn_result(initial_stop_reason),
                    mental_model_enabled=mental_model_enabled,
                    active_task_hint=context.get("active_task"),
                    user_message_source=str(context.get("user_message_source") or "").strip(),
                    turn_id=turn_id,
                )
                return

            with _capture_session_ui_stream(session_id, turn_capture, mental_model_enabled=mental_model_enabled):
                _record_session_turn_lifecycle_event(
                    session_id,
                    "ui_capture_started",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "mentalModelEnabled": mental_model_enabled,
                    },
                )
                agent_prompt_template_id = str((agent_instance or {}).get("promptTemplateId") or "").strip()
                stage_started_at = _perf_counter()
                runtime_agent = _create_chat_agent_for_session(
                    tool_workspace,
                    agent_instance=agent_instance,
                    llm_slot=llm_slot,
                    resolved_llm=resolved_agent_llm,
                )
                agent_create_ms = _elapsed_ms(stage_started_at)
                attachments = _normalize_message_attachments(context.get("attachments") or [])
                resolved_llm_model_id = str(getattr(resolved_agent_llm, "model_id", "") or "").strip() or _session_agent_llm_slot_model_id(
                    agent_instance or historical_agent,
                    llm_slot,
                )
                prompt_cache_partition = _session_prompt_cache_partition(
                    session_id=session_id,
                    agent_id=agent_id,
                    llm_slot=llm_slot,
                    llm_model_id=resolved_llm_model_id,
                    prompt_template_id=agent_prompt_template_id,
                )
                prompt_cache_scope = _session_prompt_cache_scope(agent_id=agent_id)
                _record_session_turn_lifecycle_event(
                    session_id,
                    "agent_created",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "agentType": type(runtime_agent).__name__,
                        "workspacePath": _session_workspace_relative_path(session_id),
                        "toolWorkspacePath": str(tool_workspace),
                        "dialogueModelId": agent_dialogue_model_id(agent_instance or historical_agent),
                        "llmSlot": llm_slot,
                        "llmModelId": resolved_llm_model_id,
                        "agentId": agent_id,
                        "promptTemplateId": agent_prompt_template_id,
                        **_session_prompt_cache_log_fields(scope=prompt_cache_scope, partition=prompt_cache_partition),
                        "attachmentCount": len(attachments),
                        "agentCreateMs": agent_create_ms,
                        "lightweightChatPayload": lightweight_chat_payload,
                        "lightweightChatPayloadReason": lightweight_chat_payload_reason,
                        "disableTools": lightweight_chat_payload,
                        **(resolved_agent_llm.log_fields() if resolved_agent_llm is not None else {}),
                    },
                )
                mental_override_configurer = getattr(runtime_agent, "set_mental_model_enabled_override", None)
                if callable(mental_override_configurer):
                    mental_override_configurer(mental_model_enabled)
                restore = getattr(runtime_agent, "seed_chat_history", None)
                static_runtime_context_seed = getattr(runtime_agent, "seed_static_runtime_context", None)
                runtime_context_seed = getattr(runtime_agent, "seed_runtime_context", None)
                volatile_runtime_context_seed = getattr(runtime_agent, "seed_volatile_runtime_context", None)
                stop_configurer = getattr(runtime_agent, "set_turn_interrupt_checker", None)
                if callable(stop_configurer):
                    stop_configurer(lambda: _get_turn_control_stop_reason(turn_control))
                raw_history_messages = list(context.get("history_messages") or [])
                seedable_history_messages = _history_messages_for_agent_seed(raw_history_messages)
                conversation_ledger_events = load_conversation_events(PROJECT_ROOT, session_id)
                context_assembly = assemble_conversation_context(
                    seedable_history_messages,
                    session_id=session_id,
                    current_turn_id=turn_id,
                    ledger_events=conversation_ledger_events,
                )
                history_messages = context_assembly.history_messages
                full_history_message_count = len(seedable_history_messages)
                static_runtime_context_block = (
                    str(getattr(agent_context_packet, "static_context_block", "") or "").strip()
                    if agent_context_packet is not None
                    else ""
                )
                dynamic_runtime_context_block = (
                    str(getattr(agent_context_packet, "dynamic_context_block", "") or "").strip()
                    if agent_context_packet is not None
                    else ""
                )
                runtime_context_block = (
                    str(getattr(agent_context_packet, "context_block", "") or "").strip()
                    if agent_context_packet is not None
                    else ""
                )
                if runtime_context_block and not static_runtime_context_block and not dynamic_runtime_context_block:
                    dynamic_runtime_context_block = runtime_context_block
                runtime_context_block = "\n\n".join(
                    part
                    for part in (static_runtime_context_block, dynamic_runtime_context_block)
                    if str(part or "").strip()
                ).strip()
                runtime_context_segments = (
                    list(getattr(agent_context_packet, "context_segments", []) or [])
                    if agent_context_packet is not None
                    else []
                )
                guidance_context_block = _recent_session_guidance_context_block(session_id)
                skill_invocation = context.get("skill_invocation")
                skill_runtime_context_block = _skill_runtime_context_from_invocation(skill_invocation)
                active_skill_contract = refresh_active_skill_contract_status(context.get("active_skill_contract"))
                active_skill_context_block = (
                    ""
                    if skill_runtime_context_block
                    else _active_skill_runtime_context_from_contract(active_skill_contract)
                )
                skill_runtime_context_included = False
                active_skill_context_included = False
                dynamic_runtime_context_included = False
                seed_started_at = _perf_counter()
                history_seed_ms = 0
                static_runtime_context_seed_ms = 0
                runtime_context_seed_ms = 0
                skill_context_seed_ms = 0
                active_skill_context_seed_ms = 0
                if callable(restore) and history_messages:
                    stage_started_at = _perf_counter()
                    restore(history_messages)
                    history_seed_ms = _elapsed_ms(stage_started_at)
                host_context_marker = getattr(runtime_agent, "mark_runtime_context_seeded_by_host", None)
                host_seeded_agent_context = False
                if static_runtime_context_block:
                    static_stage_started_at = _perf_counter()
                    if callable(static_runtime_context_seed):
                        static_runtime_context_seed(static_runtime_context_block)
                        host_seeded_agent_context = True
                    elif callable(runtime_context_seed):
                        legacy_context_block = (
                            runtime_context_block
                            if dynamic_runtime_context_block and not callable(volatile_runtime_context_seed)
                            else static_runtime_context_block
                        )
                        runtime_context_seed(legacy_context_block)
                        host_seeded_agent_context = True
                        dynamic_runtime_context_included = legacy_context_block == runtime_context_block and bool(
                            dynamic_runtime_context_block
                        )
                    static_runtime_context_seed_ms = _elapsed_ms(static_stage_started_at)
                if host_seeded_agent_context and callable(host_context_marker):
                    host_context_marker()
                if dynamic_runtime_context_block and callable(volatile_runtime_context_seed):
                    runtime_stage_started_at = _perf_counter()
                    volatile_runtime_context_seed(dynamic_runtime_context_block)
                    dynamic_runtime_context_included = True
                    runtime_context_seed_ms = _elapsed_ms(runtime_stage_started_at)
                if skill_runtime_context_block:
                    skill_stage_started_at = _perf_counter()
                    if callable(volatile_runtime_context_seed):
                        volatile_runtime_context_seed(skill_runtime_context_block)
                        skill_runtime_context_included = True
                    skill_context_seed_ms = _elapsed_ms(skill_stage_started_at)
                    _record_session_skill_command_event(
                        session_id,
                        turn_id=turn_id,
                        invocation=skill_invocation,
                        outcome="routed",
                    )
                if active_skill_context_block:
                    active_skill_stage_started_at = _perf_counter()
                    if callable(volatile_runtime_context_seed):
                        volatile_runtime_context_seed(active_skill_context_block)
                        active_skill_context_included = True
                    active_skill_context_seed_ms = _elapsed_ms(active_skill_stage_started_at)
                _record_session_turn_lifecycle_event(
                    session_id,
                    "history_seeded",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "rawHistoryMessageCount": len(list(context.get("history_messages") or [])),
                        "fullSeedableHistoryMessageCount": full_history_message_count,
                        "seededHistoryMessageCount": len(history_messages),
                        "historyLedgerEventCount": len(context_assembly.events),
                        "historyIncludedEventCount": len(context_assembly.included_event_ids),
                        "historyOmittedEventCount": context_assembly.omitted_event_count,
                        "historyCheckpointEventId": context_assembly.checkpoint_event_id,
                        "agentRuntimeContextIncluded": bool(static_runtime_context_block),
                        "staticRuntimeContextIncluded": bool(static_runtime_context_block),
                        "dynamicRuntimeContextIncluded": dynamic_runtime_context_included,
                        "dynamicRuntimeContextAvailable": bool(dynamic_runtime_context_block),
                        "dynamicRuntimeContextOmittedFromModelInput": bool(dynamic_runtime_context_block)
                        and not dynamic_runtime_context_included,
                        "runtimeContextSegmentCount": len(runtime_context_segments),
                        "agentRuntimeContextSkipped": bool(lightweight_chat_payload),
                        "guidanceContextIncluded": False,
                        "guidanceContextAvailable": bool(guidance_context_block),
                        "guidanceContextOmittedFromModelInput": bool(guidance_context_block),
                        "skillRuntimeContextIncluded": skill_runtime_context_included,
                        "skillRuntimeContextAvailable": bool(skill_runtime_context_block),
                        "skillRuntimeContextOmittedFromModelInput": bool(skill_runtime_context_block)
                        and not skill_runtime_context_included,
                        "skillRuntimeContextPlacement": (
                            "before_current_user"
                            if skill_runtime_context_included
                            else "omitted_no_volatile_context_seed"
                            if skill_runtime_context_block
                            else ""
                        ),
                        "activeSkillContractAvailable": bool(active_skill_contract),
                        "activeSkillContextIncluded": active_skill_context_included,
                        "activeSkillContextAvailable": bool(active_skill_context_block),
                        "activeSkillContextOmittedFromModelInput": bool(active_skill_context_block)
                        and not active_skill_context_included,
                        "activeSkillContextPlacement": (
                            "before_current_user"
                            if active_skill_context_included
                            else "omitted_no_volatile_context_seed"
                            if active_skill_context_block
                            else ""
                        ),
                        "activeSkillContractStatus": str((active_skill_contract or {}).get("status") or "").strip(),
                        "activeSkillContractSkillHash": str((active_skill_contract or {}).get("skillHash") or "").strip(),
                        "lightweightChatPayload": lightweight_chat_payload,
                        "lightweightChatPayloadReason": lightweight_chat_payload_reason,
                        "disableTools": lightweight_chat_payload,
                        "restoreAvailable": callable(restore),
                        "staticRuntimeContextSeedAvailable": callable(static_runtime_context_seed),
                        "runtimeContextSeedAvailable": callable(runtime_context_seed),
                        "volatileRuntimeContextSeedAvailable": callable(volatile_runtime_context_seed),
                        "historySeedMs": history_seed_ms,
                        "staticRuntimeContextSeedMs": static_runtime_context_seed_ms,
                        "runtimeContextSeedMs": runtime_context_seed_ms,
                        "skillContextSeedMs": skill_context_seed_ms,
                        "activeSkillContextSeedMs": active_skill_context_seed_ms,
                        "totalSeedMs": _elapsed_ms(seed_started_at),
                    },
                )

                preflight_stop_reason = _get_turn_control_stop_reason(turn_control)
                if preflight_stop_reason:
                    _record_session_turn_lifecycle_event(
                        session_id,
                        "stop_observed",
                        turn_id=turn_id,
                        outcome="stopped",
                        fields={
                            "stage": "preflight",
                            "stopReason": trim_lines(preflight_stop_reason, max_lines=2),
                        },
                    )
                    _persist_session_turn_result(
                        session_id,
                        _build_stopped_turn_result(preflight_stop_reason),
                        mental_model_enabled=mental_model_enabled,
                        active_task_hint=context.get("active_task"),
                        user_message_source=str(context.get("user_message_source") or "").strip(),
                        turn_id=turn_id,
                    )
                    return

                user_message = str(context.get("user_message") or "").strip()
                llm_attachments = _build_llm_image_attachments(session_id, attachments)
                if attachments:
                    _record_session_turn_trace_event(
                        session_id,
                        turn_id,
                        "attachments",
                        {
                            "attachmentCount": len(attachments),
                            "llmAttachmentCount": len(llm_attachments),
                            "attachments": _safe_attachment_log_summary(attachments),
                        },
                        status="running",
                        summary="User image attachments prepared for this turn.",
                    )
                context_composition = _build_last_context_composition(
                    conversation={
                        "id": session_id,
                        "agentId": agent_id,
                        "_agent": agent_instance or historical_agent,
                    },
                    turn_id=turn_id,
                    user_message=user_message,
                    history_messages=history_messages,
                    active_task=context.get("active_task"),
                    runtime_context_block=static_runtime_context_block,
                    dynamic_runtime_context_block=dynamic_runtime_context_block,
                    dynamic_runtime_context_included=dynamic_runtime_context_included,
                    runtime_context_segments=runtime_context_segments,
                    guidance_context_block=guidance_context_block,
                    guidance_context_included=False,
                    skill_runtime_context_block=skill_runtime_context_block,
                    skill_runtime_context_included=skill_runtime_context_included,
                    active_skill_context_block=active_skill_context_block,
                    active_skill_context_included=active_skill_context_included,
                    attachments=attachments,
                    prompt_cache_partition=prompt_cache_partition,
                )
                context_composition["contextAssembly"] = context_assembly.to_composition_patch()
                context_cache = (
                    context_composition.get("cache")
                    if isinstance(context_composition.get("cache"), dict)
                    else {}
                )
                _append_session_conversation_event(
                    session_id,
                    turn_id,
                    EVENT_TURN_CONTEXT,
                    status="recorded",
                    payload={
                        "historyMessageCount": len(history_messages),
                        "ledgerEventCount": len(conversation_ledger_events),
                        "historyLedgerEventCount": len(context_assembly.events),
                        "includedEventIds": list(context_assembly.included_event_ids),
                        "omittedEventCount": context_assembly.omitted_event_count,
                        "contextAssembly": context_assembly.to_composition_patch(),
                    },
                    source="session_context_assembler",
                )
                _record_session_turn_lifecycle_event(
                    session_id,
                    "context_composition_recorded",
                    turn_id=turn_id,
                    outcome="recorded",
                    fields={
                        "segmentCount": len(context_composition.get("segments") or []),
                        "totalChars": _coerce_nonnegative_int(context_composition.get("totalChars") or 0),
                        "totalTokens": _coerce_nonnegative_int(context_composition.get("totalTokens") or 0),
                        "limitTokens": _coerce_nonnegative_int(context_composition.get("limitTokens") or 0),
                        "limitSource": str(context_composition.get("limitSource") or "").strip(),
                        "limitModelId": str(context_composition.get("limitModelId") or "").strip(),
                        "limitAgentId": str(context_composition.get("limitAgentId") or "").strip(),
                        "schemaVersion": _coerce_nonnegative_int(context_composition.get("schemaVersion") or 0),
                        "cacheableSegmentCount": _coerce_nonnegative_int(
                            context_cache.get("cacheableSegmentCount") or 0
                        ),
                        "volatileSegmentCount": _coerce_nonnegative_int(
                            context_cache.get("volatileSegmentCount") or 0
                        ),
                    },
                )
                _set_session_live_context_composition(session_id, context_composition, turn_id=turn_id)
                _touch_chat_turn_work_run(
                    session_id=session_id,
                    turn_id=turn_id,
                    stage="context_composition_recorded",
                    summary=text_for(
                        get_web_language(),
                        zh=f"已组装当前轮上下文：约 {_coerce_nonnegative_int(context_composition.get('totalTokens') or 0)} tokens。",
                        en=f"Assembled this turn's context: about {_coerce_nonnegative_int(context_composition.get('totalTokens') or 0)} tokens.",
                    ),
                )
                with session_reference_context(context.get("session_references") or []):
                    result = _run_session_continuation_loop(
                        runtime_agent,
                        session_id=session_id,
                        turn_control=turn_control,
                        initial_prompt=user_message,
                        history_messages=history_messages,
                        attachments=llm_attachments,
                        user_message_source=str(context.get("user_message_source") or "").strip(),
                        prompt_cache_partition=prompt_cache_partition,
                        prompt_cache_scope=prompt_cache_scope,
                        agent_id=agent_id,
                        llm_slot=llm_slot,
                        llm_model_id=llm_model_id_for_turn,
                        disable_tools=lightweight_chat_payload,
                        allow_internal_auto_continue=bool(context.get("allow_internal_auto_continue")),
                    )
                if isinstance(result, dict):
                    result["context_composition"] = context_composition
                    result = _attach_session_llm_runtime_diagnostics(result, llm_runtime_diagnostics)
            result = _attach_turn_capture_to_result(
                result,
                turn_capture,
                mental_model_enabled=mental_model_enabled,
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "capture_attached",
                turn_id=turn_id,
                outcome="running",
                fields={
                    "hasThought": bool(turn_capture.thought),
                    "hasContent": bool(turn_capture.content),
                    "hasMentalState": bool(turn_capture.mental_state),
                    "toolCallCount": len(turn_capture.tool_calls),
                },
            )
            _persist_session_turn_result(
                session_id,
                result,
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace,
                active_task_hint=context.get("active_task"),
                user_message_source=str(context.get("user_message_source") or "").strip(),
                turn_id=turn_id,
            )
            if agent_id and _is_session_turn_current(session_id, turn_id):
                record_agent_turn_result(agent_id, session_id, result if isinstance(result, dict) else {}, run_id=turn_id)
    except Exception as exc:
        _record_session_turn_lifecycle_event(
            session_id,
            "exception",
            turn_id=turn_id,
            level="error",
            outcome="failed",
            fields={
                "exceptionType": type(exc).__name__,
                "errorPreview": trim_lines(str(exc), max_lines=2),
            },
        )
        if _is_session_turn_current(session_id, turn_id):
            _persist_session_turn_failure(session_id, context, exc)
    finally:
        _record_session_turn_lifecycle_event(
            session_id,
            "worker_finished",
            turn_id=turn_id,
            outcome="finished",
            fields={
                "wasCurrentTurn": _is_session_turn_current(session_id, turn_id),
            },
        )
        _record_session_execution_registry_event(
            session_id,
            turn_id,
            "main_agent_loop",
            "finished",
            details={"wasCurrentTurn": _is_session_turn_current(session_id, turn_id)},
        )
        _set_session_running(session_id, False, turn_id=turn_id)
        _clear_session_turn_control(session_id, turn_id=turn_id)
        _publish_session_detail_snapshot(session_id)


def _create_chat_agent_for_session(
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    resolved_llm: Any | None = None,
) -> Any:
    agent_config = getattr(resolved_llm, "config", None) or _session_agent_config_for_llm_slot(agent_instance, llm_slot)
    return call_agent_factory_with_supported_kwargs(
        create_chat_agent,
        workspace_path=session_workspace,
        config=agent_config,
    )


def create_chat_agent(workspace_path: str | Path | None = None, config: Any | None = None) -> Any:
    return create_agent_runtime(
        mode="chat",
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


def _run_session_continuation_loop(
    agent: Any,
    *,
    session_id: str,
    turn_control: SessionTurnControl | None = None,
    initial_prompt: str,
    history_messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
    user_message_source: str = "",
    prompt_cache_partition: str = "",
    prompt_cache_scope: str = "chat_session",
    agent_id: str = "",
    llm_slot: str = SESSION_LLM_SLOT_DIALOGUE,
    llm_model_id: str = "",
    disable_tools: bool = False,
    allow_internal_auto_continue: bool = False,
) -> Any:
    prompt = str(initial_prompt or "").strip()
    has_initial_attachments = bool(list(attachments or []))
    normalized_user_message_source = str(user_message_source or "").strip()
    if (
        normalized_user_message_source == "agent_inbox"
        and not has_initial_attachments
        and not _is_continue_request(prompt)
        and not _is_effective_user_message(prompt)
    ):
        _record_session_turn_lifecycle_event(
            session_id,
            "agent_inbox_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "reason": "agent_inbox_protocol_message",
                "messageLength": len(prompt),
                "fallbackSkipped": True,
            },
        )
    elif not has_initial_attachments and not _is_effective_user_message(prompt):
        _record_session_turn_lifecycle_event(
            session_id,
            "raw_dialogue_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "messageLength": len(prompt),
                "questionMarkCount": prompt.count("?"),
                "userMessageSource": normalized_user_message_source,
                "semanticRewriteSkipped": True,
            },
        )
    if _is_continue_request(prompt):
        _record_session_turn_lifecycle_event(
            session_id,
            "continue_prompt_preserved",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "messageLength": len(prompt),
                "historyMessageCount": len(history_messages),
                "semanticRewriteSkipped": True,
            },
        )

    result: Any = None
    last_visible_result: dict[str, Any] | None = None
    turn_index = 0
    while True:
        turn_index += 1
        stop_reason = _get_turn_control_stop_reason(turn_control) or _get_session_stop_reason(session_id)
        if stop_reason:
            _record_session_turn_lifecycle_event(
                session_id,
                "stop_observed",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="stopped",
                fields={
                    "stage": "continuation_preflight",
                    "turnIndex": turn_index,
                    "stopReason": trim_lines(stop_reason, max_lines=2),
                },
            )
            return _build_stopped_turn_result(stop_reason)

        _record_session_turn_lifecycle_event(
            session_id,
            "agent_turn_started",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "turnIndex": turn_index,
                "promptLength": len(prompt),
                "historyMessageCount": len(history_messages),
                "promptCacheScope": str(prompt_cache_scope or "").strip(),
                "promptCachePartition": str(prompt_cache_partition or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "llmSlot": str(llm_slot or "").strip(),
                "llmModelId": str(llm_model_id or "").strip(),
                "disableTools": bool(disable_tools),
            },
        )
        _record_session_execution_registry_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "llm_turn",
            "running",
            details={
                "turnIndex": turn_index,
                "promptLength": len(prompt),
                "disableTools": bool(disable_tools),
            },
        )
        _record_session_turn_trace_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "state",
            {"phase": "agent_turn_started", "turnIndex": turn_index},
            status="running",
            summary="Agent turn started.",
        )
        _set_session_turn_progress_live_output(
            session_id,
            "model_request",
            turn_id=getattr(turn_control, "turn_id", ""),
        )
        turn_attachments = list(attachments or []) if turn_index == 1 else []
        llm_started_at = _perf_counter()
        with prompt_cache_partition_scope(prompt_cache_partition):
            result = run_existing_agent_single_turn(
                agent,
                initial_prompt=prompt,
                attachments=turn_attachments,
                disable_tools=disable_tools,
            )
        result = _attach_session_prompt_cache_metadata(
            result,
            prompt_cache_scope=prompt_cache_scope,
            prompt_cache_partition=prompt_cache_partition,
            llm_model_id=llm_model_id,
        )
        llm_elapsed_ms = _elapsed_ms(llm_started_at)
        return_stop_reason = _get_turn_control_stop_reason(turn_control) or _get_session_stop_reason(session_id)
        if return_stop_reason:
            _record_session_turn_lifecycle_event(
                session_id,
                "stop_observed",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="stopped",
                fields={
                    "stage": "agent_return",
                    "turnIndex": turn_index,
                    "stopReason": trim_lines(return_stop_reason, max_lines=2),
                    "llmElapsedMs": llm_elapsed_ms,
                },
            )
            return _build_stopped_turn_result(return_stop_reason)

        result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else type(result).__name__
        result_visible_reply = _visible_reply_candidate(result) if isinstance(result, dict) else ""
        result_contract = build_chat_coding_result_contract(result) if isinstance(result, dict) else {}
        _record_session_turn_lifecycle_event(
            session_id,
            "agent_turn_returned",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome=result_status or "returned",
            fields={
                "turnIndex": turn_index,
                "resultStatus": result_status,
                "toolCallCount": _coerce_nonnegative_int(result.get("tool_call_count") or 0) if isinstance(result, dict) else 0,
                "hasVisibleReply": bool(result_visible_reply),
                "contractOutcome": str(result_contract.get("outcome") or "").strip().lower(),
                "explicitOutcome": _explicit_chat_result_outcome(result) if isinstance(result, dict) else "",
                "outcomeSource": _chat_result_outcome_source(result) if isinstance(result, dict) else "",
                "visibleHasConclusion": has_conclusion_signal(result_visible_reply),
                "visibleHasNextAction": has_next_action_signal(result_visible_reply),
                "isProviderFailed": _is_provider_failed_result(result),
                "llmElapsedMs": llm_elapsed_ms,
                "promptCacheScope": str(prompt_cache_scope or "").strip(),
                "promptCachePartition": str(prompt_cache_partition or "").strip(),
                "llmModelId": str(llm_model_id or "").strip(),
            },
        )
        _record_session_execution_registry_event(
            session_id,
            getattr(turn_control, "turn_id", ""),
            "llm_turn",
            result_status or "returned",
            details={
                "turnIndex": turn_index,
                "resultStatus": result_status,
                "toolCallCount": _coerce_nonnegative_int(result.get("tool_call_count") or 0) if isinstance(result, dict) else 0,
                "durationMs": llm_elapsed_ms,
            },
        )
        last_visible_result = _remember_continuation_visible_result(result, last_visible_result)
        if _is_provider_failed_result(result):
            _record_session_turn_circuit_breaker_event(
                session_id,
                result,
                turn_id=getattr(turn_control, "turn_id", ""),
                turn_index=turn_index,
            )
            return _annotate_continuation_result(result, turn_index, reached_limit=False)
        if _is_session_turn_terminal(result):
            result = _merge_continuation_visible_result(result, last_visible_result)
            terminal_visible_reply = _visible_reply_candidate(result) if isinstance(result, dict) else ""
            terminal_contract = build_chat_coding_result_contract(result) if isinstance(result, dict) else {}
            _record_session_turn_lifecycle_event(
                session_id,
                "terminal_result",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="completed",
                fields={
                    "turnIndex": turn_index,
                    "resultStatus": result_status,
                    "contractOutcome": str(terminal_contract.get("outcome") or "").strip().lower(),
                    "explicitOutcome": _explicit_chat_result_outcome(result) if isinstance(result, dict) else "",
                    "outcomeSource": _chat_result_outcome_source(result) if isinstance(result, dict) else "",
                    "visibleHasConclusion": has_conclusion_signal(terminal_visible_reply),
                    "visibleHasNextAction": has_next_action_signal(terminal_visible_reply),
                },
            )
            return _annotate_continuation_result(result, turn_index, reached_limit=False)

        if not allow_internal_auto_continue:
            paused_result = _build_auto_continue_paused_result(result, last_visible_result, turn_index)
            _record_session_turn_lifecycle_event(
                session_id,
                "followup_prompt_blocked",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="paused",
                fields={
                    "turnIndex": turn_index,
                    "reason": "internal_auto_continue_not_authorized",
                    "userMessageSource": normalized_user_message_source,
                },
            )
            return paused_result

        prompt = _build_followup_prompt(
            original_prompt=initial_prompt,
            effective_prompt=prompt,
            latest_result=result,
            history_messages=history_messages,
            turn_index=turn_index,
            guidance_summaries=_recent_session_guidance_summaries(
                session_id,
                turn_id=getattr(turn_control, "turn_id", ""),
                limit=3,
            ),
        )
        _set_session_turn_progress_live_output(
            session_id,
            "followup_prepare",
            turn_id=getattr(turn_control, "turn_id", ""),
        )
        _record_session_turn_lifecycle_event(
            session_id,
            "followup_prompt_built",
            turn_id=getattr(turn_control, "turn_id", ""),
            outcome="running",
            fields={
                "turnIndex": turn_index,
                "nextPromptLength": len(prompt),
            },
        )


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


def _persist_session_turn_result(
    session_id: str,
    result: Any,
    *,
    mental_model_enabled: bool | None = None,
    session_workspace: str | Path | None = None,
    active_task_hint: Any = None,
    user_message_source: str = "",
    turn_id: str = "",
) -> None:
    lang = get_web_language()
    capture_messages: list[dict[str, Any]] | None = None
    agent_inbox_reply: dict[str, Any] | None = None
    runtime_stop_requested = _is_session_stop_requested(session_id)
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        if turn_id and not _is_session_turn_current(session_id, turn_id):
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        if _latest_assistant_message_is_stop(messages):
            _persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=turn_id,
                status="stopped",
                summary=text_for(lang, zh="本轮已按请求停止。", en="This turn was stopped as requested."),
                finished_at=_now_timestamp(),
            )
            return
        result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else ""
        result_stop_requested = bool(result.get("stop_requested")) if isinstance(result, dict) else False
        stop_requested = result_stop_requested and runtime_stop_requested
        if _is_provider_failed_result(result):
            raw_error = _provider_failure_raw_error(result)
            error_type = _failure_error_type(raw_error)
            turn_error = _make_session_turn_error(
                raw_error,
                lang=lang,
                error_type=error_type,
                turn_id=turn_id,
                llm_failure=result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else None,
            )
            failure_message = str(turn_error.get("message") or "").strip()
            context_composition = _normalize_session_context_composition(
                result.get("context_composition") if isinstance(result, dict) else None
            )
            cache_composition = _build_session_cache_composition(turn_id, None)
            new_messages = list(messages)
            partial_reply = _provider_failure_partial_visible_reply(result, failure_message)
            partial_entry: dict[str, Any] | None = None
            if partial_reply:
                partial_entry = _make_chat_message(
                    "assistant",
                    partial_reply,
                    _extract_chat_tool_calls(result),
                    thought=_extract_chat_thought(result, partial_reply),
                    feedback_events=_extract_chat_feedback_events(result, final_status="failed"),
                    mental_snapshot=_build_turn_mental_snapshot(
                        result,
                        lang,
                        mental_model_enabled=mental_model_enabled,
                        session_workspace=session_workspace or _ensure_session_workspace(session_id),
                        session_id=session_id,
                        turn_id=turn_id,
                    ),
                )
                if isinstance(result, dict):
                    partial_entry["toolCalls"] = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
                new_messages.append(partial_entry)
            error_entry = _make_provider_failure_chat_message(
                turn_error,
                error_type=error_type,
                turn_id=turn_id,
            )
            new_messages.append(error_entry)
            timestamp = str(error_entry.get("timestamp") or _now_timestamp()).strip()
            stored_active_task = _normalize_session_active_task(
                conversation.get("active_task") or conversation.get("activeTask")
            )
            hint_active_task = _normalize_session_active_task(active_task_hint)
            existing_active_task = _select_existing_active_task_for_update(
                stored_active_task,
                hint_active_task,
                messages,
            )
            next_active_task = _build_session_active_task(
                session_id,
                result,
                messages,
                existing_task=existing_active_task,
                user_message_source=user_message_source,
            )
            _set_or_clear_session_active_task(conversation, next_active_task)
            conversation["messages"] = new_messages
            if context_composition is not None:
                conversation["last_context_composition"] = context_composition
            conversation["last_cache_composition"] = cache_composition
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)
            _clear_session_live_output(session_id, turn_id=turn_id)
            _persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=turn_id,
                status="failed",
                summary=str(turn_error.get("message") or ""),
                error_type=error_type,
                error=raw_error,
                finished_at=timestamp,
                updated_at=timestamp,
            )
            if partial_entry:
                _record_session_turn_visible_message(
                    session_id,
                    turn_id,
                    partial_entry,
                    event="assistant_partial_result",
                    status="failed_provider",
                )
                _record_session_cycle_message(
                    session_id,
                    partial_entry,
                    event="assistant_partial_result",
                    status="failed_provider",
                    active_task=next_active_task,
                )
            _record_session_turn_visible_message(
                session_id,
                turn_id,
                error_entry,
                event="assistant_turn_error",
                status="failed_provider",
            )
            _record_session_cycle_message(
                session_id,
                error_entry,
                event="assistant_turn_error",
                status="failed_provider",
                active_task=next_active_task,
            )
            _record_session_turn_result_log(
                session_id,
                turn_id,
                status="failed_provider",
                summary=str(turn_error.get("message") or ""),
                recovery_pointer={"resumeAllowed": True, "source": "provider_failure"},
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "result_persisted",
                turn_id=turn_id,
                level="error",
                outcome="failed",
                fields={
                    "resultStatus": "failed",
                    "errorType": error_type,
                    "providerFailure": error_type != "prompt_cache_unsupported",
                    "visibleErrorMessagePersisted": True,
                    "partialReplyPersisted": bool(partial_entry),
                    "messageCount": len(conversation.get("messages") or []),
                },
            )
            _record_session_turn_error(
                session_id,
                turn_error,
                raw_error=raw_error,
                status="failed",
                active_task=next_active_task,
            )
            _record_provider_failure_signal(
                session_id=session_id,
                turn_id=turn_id,
                error_type=error_type,
                raw_error=raw_error,
                related_event_code="conversation.turn_error",
            )
            if partial_entry:
                _append_session_conversation_event(
                    session_id,
                    turn_id,
                    EVENT_ASSISTANT_MESSAGE,
                    status="failed_provider",
                    payload={
                        "content": str(partial_entry.get("content") or ""),
                        "thought": str(partial_entry.get("thought") or ""),
                        "toolCalls": _normalize_message_tool_calls(partial_entry.get("tool_calls") or partial_entry.get("toolCalls") or []),
                        "feedbackEvents": _normalize_message_feedback_events(partial_entry.get("feedback_events") or partial_entry.get("feedbackEvents") or []),
                    },
                    source="persist_session_turn_result",
                )
            _append_session_conversation_event(
                session_id,
                turn_id,
                EVENT_TURN_FAILED,
                status="failed_provider",
                payload={
                    "errorType": error_type,
                    "message": str(turn_error.get("message") or ""),
                    "rawError": raw_error,
                },
                source="persist_session_turn_result",
            )
            return
        assistant_text = (
            text_for(
                lang,
                zh="本轮已按请求停止。",
                en="This turn was stopped as requested.",
            )
            if stop_requested
            else _format_visible_reply(result)
        )
        assistant_text = _ensure_assistant_visible_text(assistant_text, result=result, lang=lang)
        phantom_image_success = _is_phantom_image_generation_success(
            assistant_text,
            result,
            messages,
        )
        if phantom_image_success:
            assistant_text = text_for(
                lang,
                zh="这轮没有实际生成新的图片：系统没有捕获到图片生成工具调用产生的图片结果。请重新发送生成请求。",
                en="No new image was actually generated in this turn: no image-generation artifact was captured. Please send the generation request again.",
            )
            if isinstance(result, dict):
                result = {
                    **result,
                    "status": "failed_runtime",
                    "summary": assistant_text,
                    "raw_output": assistant_text,
                    "error": assistant_text,
                    "outcome": "failed",
                }
                result_status = "failed_runtime"
        llm_usage = _normalize_turn_llm_usage(result.get("llm_usage") if isinstance(result, dict) else None)
        if llm_usage is not None:
            llm_usage["recordedAt"] = llm_usage.get("recordedAt") or _now_timestamp()
            metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            llm_usage["promptCacheScope"] = (
                llm_usage.get("promptCacheScope")
                or metadata.get("promptCacheScope")
                or metadata.get("prompt_cache_scope")
                or "chat_session"
            )
            llm_usage["promptCachePartition"] = (
                llm_usage.get("promptCachePartition")
                or metadata.get("promptCachePartition")
                or metadata.get("prompt_cache_partition")
                or ""
            )
            llm_usage["llmModelId"] = (
                llm_usage.get("llmModelId")
                or metadata.get("llmModelId")
                or metadata.get("llm_model_id")
                or ""
            )
        context_composition = _normalize_session_context_composition(
            result.get("context_composition") if isinstance(result, dict) else None
        )
        cache_composition = _build_session_cache_composition(turn_id, llm_usage)
        final_status = _chat_turn_result_status(result_status, result, stop_requested=stop_requested)
        feedback_events_for_result = _extract_chat_feedback_events(result, final_status=final_status)
        runtime_failed = final_status in {"failed_runtime", "failed"} and not stop_requested
        if runtime_failed:
            error_type = _failure_error_type(assistant_text)
            turn_error = _make_session_turn_error(
                assistant_text,
                lang=lang,
                error_type=error_type,
                turn_id=turn_id,
            )
            assistant_entry = _make_turn_error_chat_message(
                turn_error,
                error_type=error_type,
                turn_id=turn_id,
                provider_failure=False,
            )
            assistant_entry["tool_calls"] = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
            thought = _extract_chat_thought(result, assistant_text)
            if thought:
                assistant_entry["thought"] = thought
            mental_snapshot = _build_turn_mental_snapshot(
                result,
                lang,
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace or _ensure_session_workspace(session_id),
                session_id=session_id,
                turn_id=turn_id,
            )
            if mental_snapshot is not None:
                assistant_entry["mental_snapshot"] = mental_snapshot
            normalized_feedback_events = _normalize_message_feedback_events(feedback_events_for_result)
            if normalized_feedback_events:
                assistant_entry["feedback_events"] = normalized_feedback_events
            if llm_usage is not None:
                assistant_entry["metadata"] = {
                    **(assistant_entry.get("metadata") if isinstance(assistant_entry.get("metadata"), dict) else {}),
                    "llmUsage": llm_usage,
                }
        else:
            error_type = ""
            turn_error = None
            assistant_entry = _make_chat_message(
                "assistant",
                assistant_text,
                _extract_chat_tool_calls(result),
                thought=_extract_chat_thought(result, assistant_text),
                feedback_events=feedback_events_for_result,
                mental_snapshot=_build_turn_mental_snapshot(
                    result,
                    lang,
                    mental_model_enabled=mental_model_enabled,
                    session_workspace=session_workspace or _ensure_session_workspace(session_id),
                    session_id=session_id,
                    turn_id=turn_id,
                ),
                metadata={"llmUsage": llm_usage} if llm_usage is not None else None,
            )
        assistant_metadata = assistant_entry.get("metadata") if isinstance(assistant_entry.get("metadata"), dict) else {}
        assistant_entry["metadata"] = {**assistant_metadata, "turnId": turn_id}
        if isinstance(result, dict):
            assistant_entry["toolCalls"] = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
            feedback_events = _normalize_message_feedback_events(feedback_events_for_result)
            if feedback_events:
                assistant_entry["feedbackEvents"] = feedback_events
        conversation["messages"] = messages + [assistant_entry]
        stored_active_task = _normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
        hint_active_task = _normalize_session_active_task(active_task_hint)
        existing_active_task = _select_existing_active_task_for_update(
            stored_active_task,
            hint_active_task,
            messages,
        )
        task_result = result
        if not isinstance(task_result, dict):
            task_result = {
                "status": result_status or "completed",
                "summary": assistant_text,
                "raw_output": assistant_text,
                "outcome": "done" if result_status == "completed" and not stop_requested else (result_status or ""),
            }
        next_active_task = _build_session_active_task(
            session_id,
            task_result,
            conversation["messages"],
            existing_task=existing_active_task,
            user_message_source=user_message_source,
        )
        _set_or_clear_session_active_task(conversation, next_active_task)
        if llm_usage is not None:
            conversation["last_llm_usage"] = llm_usage
        else:
            conversation["last_llm_usage"] = {
                "source": "missing",
                "inputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "cachedInputTokens": 0,
                "cacheHitRate": 0.0,
                "provider": "",
                "model": "",
                "recordedAt": _now_timestamp(),
            }
        if context_composition is not None:
            conversation["last_context_composition"] = context_composition
        conversation["last_cache_composition"] = cache_composition
        if runtime_failed and turn_error is not None:
            conversation["last_turn_error"] = turn_error
        else:
            conversation.pop("last_turn_error", None)
            conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = (
            "failed"
            if final_status in {"failed_provider", "failed_runtime", "failed"}
            else ("paused_limit" if final_status == "paused_limit" else "ready")
        )
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id, turn_id=turn_id)
        tool_calls = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
        feedback_event_count = len(_normalize_message_feedback_events(feedback_events_for_result))
        if final_status == "completed":
            capture_messages = list(conversation["messages"])
            agent_inbox_reply = _build_agent_inbox_turn_reply(
                messages,
                assistant_text=assistant_text,
                tool_calls=tool_calls,
                source_session_id=session_id,
                source_turn_id=turn_id,
            )
        cycle_active_task = next_active_task
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status=final_status,
            summary=assistant_text,
            error_type=error_type if runtime_failed else "",
            error=assistant_text if runtime_failed else "",
            finished_at=assistant_entry["timestamp"],
            updated_at=assistant_entry["timestamp"],
        )
        _record_session_turn_visible_message(
            session_id,
            turn_id,
            assistant_entry,
            event="assistant_turn_error" if runtime_failed else "assistant_result",
            status=final_status,
        )
        _record_session_turn_tool_calls(session_id, turn_id, tool_calls)
        if assistant_entry.get("thought"):
            _record_session_turn_trace_event(
                session_id,
                turn_id,
                "thought",
                {"chars": len(str(assistant_entry.get("thought") or ""))},
                status=final_status,
                summary="Assistant thought trace captured.",
            )
        _record_session_llm_usage_event(session_id, turn_id, llm_usage)
        if assistant_entry.get("mental_snapshot"):
            _record_session_turn_trace_event(
                session_id,
                turn_id,
                "mental",
                assistant_entry.get("mental_snapshot") if isinstance(assistant_entry.get("mental_snapshot"), dict) else {},
                status=final_status,
                summary="Mental model trace captured.",
            )
        if tool_calls:
            _record_session_execution_registry_event(
                session_id,
                turn_id,
                "tool_calls",
                final_status,
                details={"toolCallCount": len(tool_calls)},
            )
        _record_session_turn_result_log(
            session_id,
            turn_id,
            status=final_status,
            summary=assistant_text,
            recovery_pointer={
                "resumeAllowed": final_status in {"stopped_by_user", "paused_limit", "needs_continue"},
                "toolCallCount": len(tool_calls),
                "feedbackEventCount": feedback_event_count,
                "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
                "phantomImageSuccess": phantom_image_success,
            },
        )
        _record_session_turn_lifecycle_event(
            session_id,
            "result_persisted",
            turn_id=turn_id,
            outcome=final_status,
            fields={
                "resultStatus": result_status or "completed",
                "finalStatus": final_status,
                "errorType": error_type,
                "providerFailure": False,
                "visibleErrorMessagePersisted": bool(runtime_failed),
                "activeTaskStatus": str((cycle_active_task or {}).get("status") or "").strip(),
                "activeTaskOutcome": str(((cycle_active_task or {}).get("metadata") or {}).get("outcome") or "").strip(),
                "activeTaskChangedFileCount": len(list((cycle_active_task or {}).get("changed_files") or [])),
                "messageCount": len(conversation.get("messages") or []),
                "assistantTextLength": len(assistant_text),
                "toolCallCount": len(_extract_chat_tool_calls(result)),
                "feedbackEventCount": feedback_event_count,
                "hasThought": bool(assistant_entry.get("thought")),
                "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
                "phantomImageSuccess": phantom_image_success,
            },
        )
        if runtime_failed and turn_error is not None:
            _record_session_turn_error(
                session_id,
                turn_error,
                raw_error=assistant_text,
                status=final_status,
                active_task=cycle_active_task,
            )
        if phantom_image_success:
            _record_session_turn_lifecycle_event(
                session_id,
                "phantom_image_success_blocked",
                turn_id=turn_id,
                level="warning",
                outcome="failed_runtime",
                fields={
                    "assistantTextLength": len(assistant_text),
                    "toolCallCount": len(tool_calls),
                    "hasImageArtifactEvidence": False,
                },
            )
        _append_session_conversation_event(
            session_id,
            turn_id,
            EVENT_ASSISTANT_MESSAGE,
            status=final_status,
            payload={
                "content": assistant_text,
                "thought": str(assistant_entry.get("thought") or ""),
                "toolCalls": _normalize_message_tool_calls(assistant_entry.get("tool_calls") or assistant_entry.get("toolCalls") or []),
                "feedbackEvents": _normalize_message_feedback_events(assistant_entry.get("feedback_events") or assistant_entry.get("feedbackEvents") or []),
            },
            source="persist_session_turn_result",
        )
        terminal_event = EVENT_TURN_FAILED if final_status in {"failed_provider", "failed_runtime", "failed"} else (
            EVENT_TURN_INTERRUPTED if stop_requested or final_status in {"stopped", "stopped_by_user"} else EVENT_TURN_COMPLETED
        )
        _append_session_conversation_event(
            session_id,
            turn_id,
            terminal_event,
            status=final_status,
            payload={
                "resultStatus": result_status or "completed",
                "finalStatus": final_status,
                "marker": TURN_INTERRUPTED_MARKER if terminal_event == EVENT_TURN_INTERRUPTED else "",
                "errorType": error_type if runtime_failed else "",
                "summary": assistant_text,
            },
            source="persist_session_turn_result",
        )
    _record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_turn_error" if runtime_failed else "assistant_result",
        status=final_status,
        active_task=cycle_active_task,
    )
    if agent_inbox_reply:
        _deliver_agent_inbox_turn_reply(agent_inbox_reply)
    if capture_messages:
        _capture_session_chat_candidate(session_id, capture_messages)


def _build_agent_inbox_turn_reply(
    messages: list[dict[str, Any]],
    *,
    assistant_text: str,
    tool_calls: list[dict[str, Any]] | None = None,
    source_session_id: str,
    source_turn_id: str,
) -> dict[str, Any] | None:
    content = str(assistant_text or "").strip()
    if not content:
        return None
    inbound = _latest_agent_inbox_user_message(messages)
    if not inbound:
        return None
    metadata = inbound.get("metadata") if isinstance(inbound.get("metadata"), dict) else {}
    if str(metadata.get("inboxKind") or "").strip() == "agent_inbox_reply":
        return None
    source_agent_id = str(metadata.get("sourceAgentId") or "").strip()
    current_agent_id = str(metadata.get("targetAgentId") or "").strip()
    if not source_agent_id or not current_agent_id or source_agent_id == current_agent_id:
        return None
    original_message_id = str(metadata.get("messageId") or "").strip()
    skip_reason = _agent_inbox_auto_reply_skip_reason(
        content,
        tool_calls=tool_calls or [],
        source_agent_id=source_agent_id,
    )
    if skip_reason:
        _record_agent_inbox_reply_skipped(
            reason=skip_reason,
            source_agent_id=current_agent_id,
            target_agent_id=source_agent_id,
            original_message_id=original_message_id,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
        )
        return None
    return {
        "targetAgentId": source_agent_id,
        "sourceAgentId": current_agent_id,
        "sourceSessionId": str(source_session_id or "").strip(),
        "threadId": str(metadata.get("threadId") or original_message_id or "").strip(),
        "content": content,
        "summary": trim_lines(content, max_lines=4),
        "metadata": {
            "kind": "agent_inbox_reply",
            "replyToMessageId": original_message_id,
            "replyToTurnId": str(metadata.get("turnId") or "").strip(),
            "sourceTurnId": str(source_turn_id or "").strip(),
        },
    }


def _latest_agent_inbox_user_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in reversed(list(messages or [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() == "agent_inbox_message":
            return item
    return None


def _agent_inbox_auto_reply_skip_reason(
    assistant_text: str,
    *,
    tool_calls: list[dict[str, Any]],
    source_agent_id: str,
) -> str:
    if _agent_message_tool_sent_to_source(tool_calls, source_agent_id=source_agent_id):
        return "explicit_agent_message_sent"
    if _looks_like_agent_message_delivery_confirmation(assistant_text):
        return "operation_confirmation"
    return ""


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
        arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
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


def _record_agent_inbox_reply_skipped(
    *,
    reason: str,
    source_agent_id: str,
    target_agent_id: str,
    original_message_id: str,
    source_session_id: str,
    source_turn_id: str,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_inbox",
            "reply",
            "agent_inbox.reply_skipped",
            message="Agent inbox auto reply skipped.",
            level="info",
            outcome="skipped",
            fields={
                "reason": str(reason or "").strip(),
                "replyToMessageId": str(original_message_id or "").strip(),
                "sourceAgentId": str(source_agent_id or "").strip(),
                "targetAgentId": str(target_agent_id or "").strip(),
                "sourceSessionId": str(source_session_id or "").strip(),
                "turnId": str(source_turn_id or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _deliver_agent_inbox_turn_reply(reply: dict[str, Any]) -> None:
    target_agent_id = str(reply.get("targetAgentId") or "").strip()
    source_agent_id = str(reply.get("sourceAgentId") or "").strip()
    if not target_agent_id or not source_agent_id:
        return
    try:
        message = agent_directory_service.write_agent_inbox_message(
            target_agent_id,
            content=str(reply.get("content") or ""),
            source_agent_id=source_agent_id,
            source_session_id=str(reply.get("sourceSessionId") or "").strip(),
            thread_id=str(reply.get("threadId") or "").strip(),
            kind="agent_inbox_reply",
            summary=str(reply.get("summary") or "").strip(),
            metadata=reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {},
        )
        delivery = wake_agent_for_inbox_message(message)
        _record_agent_inbox_reply_event("agent_inbox.reply_delivered", message, delivery, outcome="delivered")
    except Exception as exc:
        _record_agent_inbox_reply_event(
            "agent_inbox.reply_failed",
            {
                "sourceAgentId": source_agent_id,
                "targetAgentId": target_agent_id,
                "metadata": reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {},
            },
            {"wakeStatus": "failed", "reason": type(exc).__name__},
            level="warning",
            outcome="failed",
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


def _persist_session_turn_runtime_error(
    session_id: str,
    turn_error: dict[str, Any],
    *,
    raw_error: str,
    turn_id: str = "",
    status: str = "failed_runtime",
    work_run_summary: str = "",
) -> None:
    timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
    error_entry = _make_local_runtime_error_chat_message(turn_error, turn_id=turn_id)
    message = str(error_entry.get("content") or turn_error.get("message") or "").strip()
    normalized_status = str(status or "failed_runtime").strip() or "failed_runtime"
    normalized_error_type = str(turn_error.get("error_type") or turn_error.get("errorType") or "runtime_error").strip()
    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        if turn_id and not _is_session_turn_current(session_id, turn_id):
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        conversation["messages"] = messages + [error_entry]
        conversation["last_turn_status"] = normalized_status
        conversation["last_turn_error"] = turn_error
        conversation["updated_at"] = timestamp
        payload["updated_at"] = timestamp
        save_chat_state(PROJECT_ROOT, payload)
    _clear_session_live_output(session_id, turn_id=turn_id)
    _persist_chat_turn_work_run(
        session_id=session_id,
        turn_id=turn_id,
        status=normalized_status,
        summary=work_run_summary or message,
        error_type=normalized_error_type,
        error=raw_error,
        finished_at=timestamp,
        updated_at=timestamp,
    )
    _record_session_turn_result_log(
        session_id,
        turn_id,
        status=normalized_status,
        summary=message,
        recovery_pointer={"resumeAllowed": False, "source": "local_runtime_error"},
    )
    _record_session_turn_visible_message(
        session_id,
        turn_id,
        error_entry,
        event="assistant_turn_error",
        status=normalized_status,
    )
    _record_session_cycle_message(
        session_id,
        error_entry,
        event="assistant_turn_error",
        status=normalized_status,
    )
    _record_session_turn_lifecycle_event(
        session_id,
        "runtime_error_persisted",
        turn_id=turn_id,
        level="error",
        outcome=normalized_status,
        fields={
            "errorType": normalized_error_type,
            "reasonCode": str(turn_error.get("reason_code") or turn_error.get("reasonCode") or "").strip(),
            "model": str(turn_error.get("model") or "").strip(),
            "visibleTurnErrorMessagePersisted": True,
            "normalAssistantReplyPersisted": False,
        },
    )
    _record_session_turn_error(
        session_id,
        turn_error,
        raw_error=raw_error,
        status=normalized_status,
    )
    _append_session_conversation_event(
        session_id,
        turn_id,
        EVENT_TURN_FAILED,
        status=normalized_status,
        payload={
            "errorType": normalized_error_type,
            "message": message,
            "rawError": raw_error,
        },
        source="persist_session_turn_runtime_error",
    )


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
        },
    )
    message["timestamp"] = timestamp
    return message


def _record_agent_inbox_reply_event(
    event_code: str,
    message: dict[str, Any],
    delivery: dict[str, Any],
    *,
    level: str = "info",
    outcome: str = "observed",
) -> None:
    try:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        record_runtime_scene_event(
            "agent_inbox",
            "reply",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
                "replyToMessageId": str(metadata.get("replyToMessageId") or "").strip(),
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(message.get("targetAgentId") or "").strip(),
                "targetSessionId": str(delivery.get("targetSessionId") or "").strip(),
                "turnId": str(delivery.get("turnId") or "").strip(),
                "wakeStatus": str(delivery.get("wakeStatus") or "").strip(),
                "reason": str(delivery.get("reason") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _persist_session_turn_failure(session_id: str, context: dict[str, Any], exc: Exception) -> None:
    lang = get_web_language()
    raw_error = str(exc or "").strip()
    error_type = _failure_error_type(raw_error, exc=exc)
    turn_id = str(context.get("turn_id") or "")
    summary = _user_visible_failure_summary(raw_error, lang=lang, exc=exc)
    work_run_summary = text_for(
        lang,
        zh="网页工作台这一轮执行失败，完整错误已写入运行日志。",
        en="This web workbench turn failed. The full error was written to runtime logs.",
    )

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        if _looks_like_provider_error_text(raw_error):
            turn_error = _make_session_turn_error(raw_error, lang=lang, error_type=error_type, turn_id=turn_id)
            error_entry = _make_provider_failure_chat_message(
                turn_error,
                error_type=error_type,
                turn_id=turn_id,
            )
            timestamp = str(error_entry.get("timestamp") or _now_timestamp()).strip()
            conversation["messages"] = messages + [error_entry]
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)
            _clear_session_live_output(session_id, turn_id=turn_id)
            _persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=turn_id,
                status="failed",
                summary=work_run_summary,
                error_type=error_type,
                error=raw_error,
                finished_at=timestamp,
                updated_at=timestamp,
            )
            _record_session_turn_result_log(
                session_id,
                turn_id,
                status="failed_provider",
                summary=work_run_summary,
                recovery_pointer={"resumeAllowed": True, "source": "provider_failure"},
            )
            _record_session_turn_visible_message(
                session_id,
                turn_id,
                error_entry,
                event="assistant_turn_error",
                status="failed_provider",
            )
            _record_session_cycle_message(
                session_id,
                error_entry,
                event="assistant_turn_error",
                status="failed_provider",
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "failure_persisted",
                turn_id=turn_id,
                level="error",
                outcome="failed",
                fields={
                    "errorType": error_type,
                    "providerFailure": True,
                    "visibleErrorMessagePersisted": True,
                    "messageCount": len(conversation.get("messages") or []),
                },
            )
            _record_session_turn_error(
                session_id,
                turn_error,
                raw_error=raw_error,
                status="failed",
            )
            _record_provider_failure_signal(
                session_id=session_id,
                turn_id=turn_id,
                error_type=error_type,
                raw_error=raw_error,
                related_event_code="conversation.turn_error",
            )
            _append_session_conversation_event(
                session_id,
                turn_id,
                EVENT_TURN_FAILED,
                status="failed_provider",
                payload={
                    "errorType": error_type,
                    "message": str(turn_error.get("message") or ""),
                    "rawError": raw_error,
                },
                source="persist_session_turn_failure",
            )
            return
        turn_error = _make_session_turn_error(raw_error, lang=lang, error_type=error_type, turn_id=turn_id)
        error_entry = _make_turn_error_chat_message(
            turn_error,
            error_type=error_type,
            turn_id=turn_id,
            provider_failure=False,
        )
        timestamp = str(error_entry.get("timestamp") or _now_timestamp()).strip()
        conversation["messages"] = messages + [error_entry]
        conversation["last_turn_error"] = turn_error
        conversation["last_turn_status"] = "failed"
        conversation["updated_at"] = timestamp
        payload["updated_at"] = timestamp
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id, turn_id=turn_id)
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="failed",
            summary=work_run_summary,
            error_type=error_type,
            error=raw_error,
            finished_at=timestamp,
            updated_at=timestamp,
        )
        _record_session_turn_visible_message(
            session_id,
            turn_id,
            error_entry,
            event="assistant_turn_error",
            status="failed",
        )
        _record_session_turn_result_log(
            session_id,
            turn_id,
            status="failed_runtime",
            summary=work_run_summary,
            recovery_pointer={"resumeAllowed": True, "source": "runtime_failure"},
        )
        _record_session_turn_lifecycle_event(
            session_id,
            "failure_persisted",
            turn_id=turn_id,
            level="error",
            outcome="failed",
            fields={
                "errorType": error_type,
                "providerFailure": False,
                "visibleErrorMessagePersisted": True,
                "messageCount": len(conversation.get("messages") or []),
            },
        )
        _record_session_turn_error(
            session_id,
            turn_error,
            raw_error=raw_error,
            status="failed",
        )
    _record_session_cycle_message(
        session_id,
        error_entry,
        event="assistant_turn_error",
        status="failed",
    )
    _append_session_conversation_event(
        session_id,
        turn_id,
        EVENT_TURN_FAILED,
        status="failed_runtime",
        payload={
            "errorType": error_type,
            "message": str(turn_error.get("message") or ""),
            "rawError": raw_error,
        },
        source="persist_session_turn_failure",
    )


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


def _format_agent_inbox_wake_prompt(message: dict[str, Any]) -> str:
    source_code = str(message.get("sourceAgentCode") or "").strip()
    source_name = str(message.get("sourceAgentName") or "").strip()
    source_agent_id = str(message.get("sourceAgentId") or "").strip()
    source_label = " · ".join(item for item in (source_code, source_name) if item) or source_agent_id or "外部来源"
    inbox_kind = str(message.get("kind") or "").strip()
    content = str(message.get("content") or "").strip()
    summary = trim_lines(str(message.get("summary") or ""), max_lines=4)
    lines = [
        "[Agent 私信回复]" if inbox_kind == "agent_inbox_reply" else "[Agent 私信]",
        f"来源 Agent: {source_label}",
        f"消息ID: {message.get('messageId') or message.get('eventId') or ''}",
    ]
    if message.get("sourceRoomId") or message.get("sourceRoundId"):
        lines.append(f"来源群聊: {message.get('sourceRoomId') or ''} / {message.get('sourceRoundId') or ''}")
    if summary and summary != content:
        lines.extend(["", "摘要:", summary])
    lines.extend(
        [
            "",
            "消息内容:",
            content,
            "",
            (
                "这是其他 Agent 对你此前私信或任务请求的回复。请基于你的身份和当前会话目标，面向当前用户或当前任务汇总这条回复；除非确实需要继续追问，不要再把确认消息发回来源 Agent。"
                if inbox_kind == "agent_inbox_reply"
                else "请基于你的身份、当前会话上下文和可用信息回复这条来自其他 Agent 的消息。"
            ),
        ]
    )
    return "\n".join(str(line) for line in lines if str(line).strip() or line == "").strip()


def _record_agent_inbox_wake_event(
    event_code: str,
    message: dict[str, Any],
    delivery: dict[str, Any],
    *,
    level: str,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_inbox",
            "wake",
            event_code,
            message=event_code,
            level=level,
            outcome=str(delivery.get("wakeStatus") or "").strip() or "observed",
            fields={
                "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(message.get("targetAgentId") or "").strip(),
                "targetSessionId": str(delivery.get("targetSessionId") or "").strip(),
                "turnId": str(delivery.get("turnId") or "").strip(),
                "wakeStatus": str(delivery.get("wakeStatus") or "").strip(),
                "reason": str(delivery.get("reason") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


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


def _record_cli_agent_lifecycle_event(
    session_id: str,
    *,
    event: str,
    metadata: dict[str, Any],
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "cli_agent",
            "conversation.cli_agent.lifecycle",
            level="info",
            outcome=str(event or "").strip() or "updated",
            message="CLI Agent lifecycle event recorded in conversation history.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "event": str(event or "").strip(),
                "cliRunId": str(metadata.get("cliRunId") or "").strip(),
                "terminalSessionId": str(metadata.get("terminalSessionId") or "").strip(),
                "adapterId": str(metadata.get("adapterId") or "").strip(),
                "sourceRunId": str(metadata.get("sourceRunId") or "").strip(),
                "cliSessionIdPresent": bool(str(metadata.get("cliSessionId") or "").strip()),
                "cliSessionIdSource": str(metadata.get("cliSessionIdSource") or "").strip(),
                "linkedSourceRunCount": len(list(metadata.get("linkedSourceRunIds") or [])),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene cli lifecycle log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_cli_agent_task_result_event(
    session_id: str,
    *,
    task_result: dict[str, Any],
    wake_status: str = "",
    signal_id: str = "",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "cli_agent",
            "conversation.cli_agent.task_result",
            level="warning" if str(task_result.get("status") or "").strip().lower() in {"failed", "timeout", "error"} else "info",
            outcome=str(task_result.get("status") or "").strip() or "updated",
            message="CLI Agent task result recorded in conversation history.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "taskId": str(task_result.get("taskId") or "").strip(),
                "status": str(task_result.get("status") or "").strip(),
                "code": str(task_result.get("code") or "").strip(),
                "terminalSessionId": str(task_result.get("terminalSessionId") or "").strip(),
                "adapterId": str(task_result.get("adapterId") or task_result.get("agentType") or "").strip(),
                "cliRunId": str(task_result.get("cliRunId") or "").strip(),
                "wakeStatus": str(wake_status or "").strip(),
                "signalId": str(signal_id or "").strip(),
                "segmentCount": len(list(task_result.get("resultSegments") or [])),
            },
            lifecycle=True,
        )
    except Exception as exc:
        _debug_logger.warning(
            f"runtime scene cli task result log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
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
            "attachmentCount": len(_normalize_message_attachments(context.get("attachments") or [])),
            **submit_timing_fields,
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
    try:
        record_runtime_scene_event(
            "conversation",
            "llm_usage",
            "conversation.llm_usage.recorded" if observed else "conversation.llm_usage.missing",
            level="info" if observed else "warning",
            outcome="recorded" if observed else "missing",
            message="Conversation turn LLM usage recorded." if observed else "Conversation turn LLM usage missing.",
            fields=fields,
            child_log_path=f"conversations/{_safe_session_workspace_token(str(session_id or '').strip())}-turns.jsonl",
            child_log_payload=fields,
            lifecycle=False,
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


def _record_direct_session_agent_deleted_event(
    result: dict[str, Any],
    *,
    previous_status: str,
    created_tombstone: bool,
    level: str = "warning",
) -> None:
    outcome = "failed" if str(result.get("reason") or "") == "tombstone_failed" else "persisted"
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_binding",
            "conversation.agent_deleted_tombstone.persisted",
            message="Direct session was preserved with a deleted-Agent tombstone after Agent purge.",
            level=level,
            outcome=outcome,
            fields={
                "sessionId": str(result.get("sessionId") or "").strip(),
                "agentId": str(result.get("agentId") or "").strip(),
                "agentStatusCode": str(result.get("agentStatusCode") or "").strip(),
                "previousStatus": str(previous_status or "").strip(),
                "historyRetention": str(result.get("historyRetention") or "").strip(),
                "createdTombstoneConversation": bool(created_tombstone),
                "reason": str(result.get("reason") or "").strip(),
                "errorType": str(result.get("errorType") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_direct_session_agent_deleted_rollback_event(
    result: dict[str, Any],
    *,
    level: str = "info",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_binding",
            "conversation.agent_deleted_tombstone.rollback",
            message="Direct-session deleted-Agent tombstone was rolled back after Agent purge failed.",
            level=level,
            outcome="failed" if str(result.get("reason") or "") == "restore_failed" else "rolled_back",
            fields={
                "sessionId": str(result.get("sessionId") or "").strip(),
                "agentId": str(result.get("agentId") or "").strip(),
                "changed": bool(result.get("changed")),
                "reason": str(result.get("reason") or "").strip(),
                "errorType": str(result.get("errorType") or "").strip(),
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


def _record_session_detail_snapshot_published_event(
    *,
    session_id: str,
    elapsed_ms: int,
    subscriber_count: int,
    delivered_count: int,
    dropped_count: int,
    message_count: int,
    current_phase: str,
) -> None:
    if subscriber_count <= 0:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.detail_snapshot.published",
            level="info",
            outcome="published",
            message="Session detail snapshot was published to active SSE subscribers.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "elapsedMs": max(0, int(elapsed_ms)),
                "subscriberCount": max(0, int(subscriber_count)),
                "deliveredCount": max(0, int(delivered_count)),
                "droppedCount": max(0, int(dropped_count)),
                "messageCount": max(0, int(message_count)),
                "currentPhase": str(current_phase or "").strip(),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_session_detail_snapshot_throttled_event(
    *,
    session_id: str,
    subscriber_count: int,
    skipped_count: int,
    current_phase: str,
    interval_ms: int,
) -> None:
    if subscriber_count <= 0:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.detail_snapshot.throttled",
            level="info",
            outcome="skipped",
            message="Session detail snapshot publish was throttled for a busy session.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "subscriberCount": max(0, int(subscriber_count)),
                "skippedCount": max(0, int(skipped_count)),
                "currentPhase": str(current_phase or "").strip(),
                "minIntervalMs": max(0, int(interval_ms)),
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
    return f"conversations/{session_token}/{turn_token}/{file_token or 'trace_events.jsonl'}"


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
        if status in {"success", "succeeded", "completed", "finished", "ready"}:
            return "done"
        if status in {"error", "timeout", "timed_out"}:
            return "failed"
        return status
    return default


def _trim_tool_detail_text(value: Any, *, max_chars: int = 1200, max_lines: int = 12) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines]).strip()
    else:
        text = "\n".join(lines).strip()
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
            if _looks_like_tool_call_failure_summary(summary or item.get("error") or ""):
                entry["status"] = "failed"
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
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "tracePath",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["name"]:
            tool_calls.append(entry)
    return tool_calls


def _normalize_feedback_event_kind(value: Any) -> str:
    kind = str(value or "").strip().lower()
    if kind in {"thought", "mental", "tool", "status"}:
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
            "tracePath",
            "relatedThoughtSequence",
        ):
            if key in item:
                entry[key] = item[key]
        if entry["sequence"] > 0 and entry["kind"]:
            events.append(entry)
    return events


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
) -> dict[str, Any]:
    normalized_error_type = str(error_type or _failure_error_type(str(raw_error or ""))).strip() or "runtime_error"
    provider_reason = _provider_error_user_reason(raw_error, lang=lang)
    provider_diagnostics = _provider_error_diagnostics(raw_error, llm_failure=llm_failure)
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
    return {
        "message": _user_visible_failure_summary(raw_error, lang=lang, provider_reason=provider_reason),
        "error_type": normalized_error_type,
        "reason_code": provider_reason["code"],
        "reason_summary": provider_reason["summary"],
        "reason_detail": provider_reason["detail"],
        "http_status": provider_diagnostics.get("http_status") or 0,
        "provider": provider_diagnostics.get("provider") or "",
        "provider_host": provider_diagnostics.get("provider_host") or "",
        "provider_error_type": provider_diagnostics.get("provider_error_type") or "",
        "provider_error_message": provider_diagnostics.get("provider_error_message") or "",
        "model": provider_diagnostics.get("model") or "",
        "recoverable": normalized_error_type.startswith("provider_") or normalized_error_type in {"server_error", "network_error"},
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
    if status_key not in {"completed", "done", "ready"}:
        for index, item in enumerate(events):
            if str(item.get("status") or "").strip().lower() in {"running", "pending"}:
                latest_unfinished_index = index
    for index, item in enumerate(events):
        entry = dict(item)
        if str(entry.get("status") or "").strip().lower() in {"running", "pending"}:
            entry["status"] = (
                "done"
                if status_key in {"completed", "done", "ready"} or index < latest_unfinished_index
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
    lower = value.lower()
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
    if override is not None:
        return bool(override)
    return is_mental_model_enabled()


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


def _record_session_assistant_delta_published_event(
    *,
    session_id: str,
    turn_id: str,
    stage: str,
    elapsed_ms: int,
    subscriber_count: int,
    delivered_count: int,
    dropped_count: int,
    content_chars: int,
    thought_chars: int,
    done: bool,
) -> None:
    if subscriber_count <= 0:
        return
    try:
        record_runtime_scene_event(
            "conversation",
            "session_stream",
            "session.assistant_delta.published",
            level="info",
            outcome="published",
            message="Session assistant live output was published to active SSE subscribers.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "stage": str(stage or "").strip(),
                "elapsedMs": max(0, int(elapsed_ms)),
                "subscriberCount": max(0, int(subscriber_count)),
                "deliveredCount": max(0, int(delivered_count)),
                "droppedCount": max(0, int(dropped_count)),
                "contentChars": max(0, int(content_chars)),
                "thoughtChars": max(0, int(thought_chars)),
                "done": bool(done),
            },
            lifecycle=False,
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


def _messages_with_live_output(session_id: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detail_messages = _merge_cli_agent_lifecycle_sidecar_messages(
        session_id,
        _normalize_messages(session_id, messages),
    )
    live_message = _build_live_output_message(session_id)
    if live_message is None:
        return detail_messages
    return detail_messages + [live_message]


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
) -> None:
    requested_turn_id = str(turn_id or "").strip()
    assistant_delta_state: SessionLiveOutputState | None = None
    checkpoint_snapshot: SessionLiveOutputState | None = None
    delete_checkpoint = False
    publish_full_snapshot = not (
        stage is _UNSET
        and mental_snapshot is _UNSET
        and tool_calls is _UNSET
        and context_composition is _UNSET
        and (content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET)
    )
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
        state.updated_at = _now_timestamp()
        if (
            not state.thought
            and not state.content
            and state.mental_snapshot is None
            and not state.tool_calls
            and not state.feedback_events
            and state.context_composition is None
        ):
            if content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET:
                assistant_delta_state = SessionLiveOutputState(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    stage=state.stage,
                    thought_delta=thought_delta,
                    content_delta=content_delta,
                    replace_thought=replace_thought,
                    replace_content=replace_content,
                    feedback_events=list(state.feedback_events or []),
                    updated_at=state.updated_at,
                )
            _SESSION_LIVE_OUTPUTS.pop(session_id, None)
            delete_checkpoint = True
        elif content is not _UNSET or thought is not _UNSET or feedback_events is not _UNSET:
            assistant_delta_state = SessionLiveOutputState(
                session_id=state.session_id,
                turn_id=state.turn_id,
                stage=state.stage,
                thought_delta=thought_delta,
                content_delta=content_delta,
                replace_thought=replace_thought,
                replace_content=replace_content,
                feedback_events=list(state.feedback_events or []),
                updated_at=state.updated_at,
            )
        if state.turn_id and (
            content is not _UNSET
            or thought is not _UNSET
            or tool_calls is not _UNSET
            or feedback_events is not _UNSET
            or mental_snapshot is not _UNSET
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
                updated_at=state.updated_at,
            )
    if delete_checkpoint:
        _delete_session_live_output_checkpoint(session_id)
    elif checkpoint_snapshot is not None:
        _write_session_live_output_checkpoint(session_id, checkpoint_snapshot)
    if assistant_delta_state is not None:
        _publish_session_assistant_delta(session_id, assistant_delta_state)
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


def _current_session_live_context_composition(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return _normalize_session_context_composition(state.context_composition)


def _seed_capture_from_live_feedback_events(session_id: str, capture: SessionTurnCapture) -> None:
    live_state = _snapshot_session_live_output(session_id)
    if live_state is None:
        return
    live_turn_id = str(live_state.turn_id or "").strip()
    if live_turn_id and capture.turn_id and live_turn_id != capture.turn_id:
        return
    events = _normalize_message_feedback_events(live_state.feedback_events)
    if not events:
        return
    capture.feedback_events = events
    capture._next_feedback_sequence = max(_coerce_nonnegative_int(item.get("sequence")) for item in events) + 1
    latest_thought = 0
    for item in events:
        if item.get("kind") == "thought":
            latest_thought = _coerce_nonnegative_int(item.get("sequence"))
    capture._latest_thought_sequence = latest_thought


def _active_session_turn_capture(session_id: str, turn_id: str = "") -> SessionTurnCapture | None:
    context = _SESSION_UI_CAPTURE_CONTEXT.get({})
    if not isinstance(context, dict):
        return None
    capture = context.get("capture")
    if not isinstance(capture, SessionTurnCapture):
        return None
    expected_session_id = str(context.get("sessionId") or "").strip()
    if expected_session_id and expected_session_id != str(session_id or "").strip():
        return None
    requested_turn_id = str(turn_id or "").strip()
    if requested_turn_id and capture.turn_id and requested_turn_id != capture.turn_id:
        return None
    return capture


def _touch_chat_turn_work_run(
    *,
    session_id: str,
    turn_id: str,
    stage: str,
    summary: str = "",
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
            zh="正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
            en="Thinking; reasoning chunks are arriving...\nThe model is returning reasoning and visible text may follow.",
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
        content=content,
        feedback_events=feedback_events,
    )
    _touch_chat_turn_work_run(session_id=session_id, turn_id=turn_id, stage=stage_key, summary=trim_lines(content, max_lines=1))
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
    fallback_profile_id = str(data.get("fallback_profile_id") or data.get("fallbackProfileId") or "").strip()
    content_chars = _coerce_nonnegative_int(data.get("content_chars") or data.get("contentChars"))

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
    elif status_key == "fallback_invoke_started":
        reason_line = category or text_for(language, zh="连续流式失败", en="repeated stream failure")
        profile_line = f"\nFallback: {fallback_profile_id}" if fallback_profile_id else ""
        content = text_for(
            language,
            zh=f"流式输出不稳定，正在切换到非流式回答...\n原因：{reason_line}。{profile_line}",
            en=f"Streaming is unstable; switching to a non-streaming response...\nReason: {reason_line}.{profile_line}",
        )
        stage = "model_fallback"
    elif status_key == "fallback_invoke_succeeded":
        content = text_for(
            language,
            zh=f"非流式回答已返回，正在写入会话...\n正文约 {content_chars} 个字符。",
            en=f"The non-streaming response returned and is being written to the session...\nAbout {content_chars} characters.",
        )
        stage = "model_fallback"
    elif status_key == "failed":
        reason_line = category or text_for(language, zh="模型调用失败", en="model call failed")
        content = text_for(
            language,
            zh=f"模型请求失败。\n原因：{reason_line}。",
            en=f"The model request failed.\nReason: {reason_line}.",
        )
        stage = "model_failed"
    else:
        return

    feedback_events = _append_session_live_feedback_event(
        session_id,
        {
            "kind": "status",
            "status": "failed" if status_key == "failed" else "running",
            "name": status_key or stage,
            "summary": trim_lines(content, max_lines=2),
            "resultPreview": content,
        },
        turn_id=turn_id,
    )
    capture = _active_session_turn_capture(session_id, turn_id)
    if capture is not None:
        capture.note_status_event(status_key or stage, content, status="failed" if status_key == "failed" else "running", name=status_key or stage)
        feedback_events = list(capture.feedback_events)
    _set_session_live_output(
        session_id,
        turn_id=turn_id,
        stage=stage,
        content=content,
        feedback_events=feedback_events,
    )
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
            "fallbackProfileId": fallback_profile_id,
            "contentChars": content_chars,
            "messageLength": len(content),
        },
    )


def _set_session_model_thinking_live_output(session_id: str, *, turn_id: str = "", thought_chars: int = 0) -> None:
    live_state = _snapshot_session_live_output(session_id)
    if live_state is not None and str(live_state.stage or "").strip() == "model_thinking":
        return
    _set_session_turn_progress_live_output(session_id, "model_thinking", turn_id=turn_id)
    _record_session_turn_lifecycle_event(
        session_id,
        "llm_status_reasoning",
        turn_id=turn_id,
        outcome="running",
        fields={
            "llmStatus": "reasoning",
            "thoughtChars": max(0, int(thought_chars or 0)),
        },
    )


def _clear_session_live_output(session_id: str, *, turn_id: str = "") -> None:
    requested_turn_id = str(turn_id or "").strip()
    should_delete_checkpoint = False
    with _SESSION_LIVE_OUTPUTS_LOCK:
        if requested_turn_id:
            current = _SESSION_LIVE_OUTPUTS.get(session_id)
            if current is not None and current.turn_id and current.turn_id != requested_turn_id:
                return
        _SESSION_LIVE_OUTPUTS.pop(session_id, None)
        should_delete_checkpoint = True
    if should_delete_checkpoint:
        _delete_session_live_output_checkpoint(session_id)


def _snapshot_session_live_output(session_id: str) -> SessionLiveOutputState | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return SessionLiveOutputState(
            session_id=session_id,
            turn_id=state.turn_id,
            stage=state.stage,
            thought=state.thought,
            content=state.content,
            mental_snapshot=dict(state.mental_snapshot or {}) if isinstance(state.mental_snapshot, dict) else None,
            tool_calls=list(state.tool_calls or []),
            feedback_events=list(state.feedback_events or []),
            context_composition=dict(state.context_composition or {}) if isinstance(state.context_composition, dict) else None,
            updated_at=state.updated_at,
        )


def _persist_session_interrupted_snapshot(
    session_id: str,
    stop_snapshot: dict[str, Any],
    *,
    lang: str,
) -> None:
    reason = str(stop_snapshot.get("stopReason") or "").strip()
    turn_id = str(stop_snapshot.get("turnId") or "").strip()
    live_state = _snapshot_session_live_output(session_id)
    live_content = _sanitize_message_content("assistant", getattr(live_state, "content", "") if live_state else "")
    live_thought = _sanitize_thought_text(getattr(live_state, "thought", "") if live_state else "")
    live_tools = _normalize_message_tool_calls(getattr(live_state, "tool_calls", []) if live_state else [])
    live_feedback_events = _normalize_message_feedback_events(getattr(live_state, "feedback_events", []) if live_state else [])
    live_mental = _normalize_mental_snapshot(getattr(live_state, "mental_snapshot", None) if live_state else None)
    live_stage = str(getattr(live_state, "stage", "") if live_state else "").strip().lower()
    stop_text = text_for(
        lang,
        zh="本轮已按请求停止。可发送“继续”恢复这次未完成的任务。",
        en='This turn was stopped as requested. Send "continue" to resume the unfinished task.',
    )
    assistant_text = f"{live_content}\n\n{stop_text}".strip() if live_content else stop_text
    queued_before_worker = (
        live_stage == "queued"
        and not live_thought
        and not live_tools
        and live_mental is None
    )

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, session_id)
        if conversation is None:
            return
        messages = normalize_chat_messages(conversation.get("messages") or [])
        if _latest_assistant_message_is_stop(messages):
            conversation["last_turn_status"] = "ready"
            payload["updated_at"] = conversation.get("updated_at") or _now_timestamp()
            save_chat_state(PROJECT_ROOT, payload)
            _clear_session_live_output(session_id)
            return
        if queued_before_worker:
            stopped_at = str(stop_snapshot.get("stopRequestedAt") or "").strip() or _now_timestamp()
            notice_message = text_for(
                lang,
                zh="本轮已按请求停止，尚未开始执行。",
                en="This turn was stopped before it started.",
            )
            conversation["runtime_notices"] = _append_session_runtime_notice(
                conversation.get("runtime_notices") or conversation.get("runtimeNotices") or [],
                {
                    "kind": "turn_stopped",
                    "level": "info",
                    "message": notice_message,
                    "timestamp": stopped_at,
                    "source": "conversation.turn_stopped_before_start",
                    "turnId": turn_id,
                    "previousStatus": "queued",
                },
            )
            conversation["last_turn_status"] = "ready"
            conversation["updated_at"] = stopped_at
            payload["updated_at"] = stopped_at
            save_chat_state(PROJECT_ROOT, payload)
            _persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=turn_id,
                status="stopped",
                summary=notice_message,
                finished_at=stopped_at,
                updated_at=stopped_at,
            )
            _clear_session_live_output(session_id)
            _record_session_turn_lifecycle_event(
                session_id,
                "queued_stop_not_persisted",
                turn_id=turn_id,
                outcome="stopped",
                fields={
                    "reason": "queued_before_worker_start",
                    "messageCount": len(messages),
                },
            )
            _append_session_conversation_event(
                session_id,
                turn_id,
                EVENT_TURN_INTERRUPTED,
                status="stopped",
                payload={
                    "reason": reason or "queued_before_worker_start",
                    "marker": TURN_INTERRUPTED_MARKER,
                    "summary": notice_message,
                },
                source="persist_interrupted_snapshot",
            )
            return
        existing_active_task = _normalize_session_active_task(
            conversation.get("active_task") or conversation.get("activeTask")
        )
        stopped_result = {
            "status": "stopped",
            "summary": assistant_text,
            "raw_output": assistant_text,
            "thought": live_thought,
            "stop_requested": True,
            "stop_reason": reason,
            "outcome": "progress",
            "recommended_next_action": text_for(
                lang,
                zh="发送“继续”以恢复停止前的现场。",
                en='Send "continue" to resume from the stopped point.',
            ),
            "tool_call_count": len(live_tools),
            "tool_trace": live_tools,
            "feedback_events": live_feedback_events,
        }
        assistant_entry = _make_chat_message(
            "assistant",
            assistant_text,
            live_tools,
            thought=live_thought,
            feedback_events=live_feedback_events,
            mental_snapshot=live_mental,
            metadata={"turnId": turn_id},
        )
        if live_tools:
            assistant_entry["toolCalls"] = live_tools
        if live_feedback_events:
            assistant_entry["feedbackEvents"] = live_feedback_events
        conversation["messages"] = messages + [assistant_entry]
        next_active_task = _build_session_active_task(
            session_id,
            stopped_result,
            conversation["messages"],
            existing_task=existing_active_task,
        )
        _set_or_clear_session_active_task(conversation, next_active_task)
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="stopped",
            summary=assistant_text,
            finished_at=assistant_entry["timestamp"],
            updated_at=assistant_entry["timestamp"],
        )
    _clear_session_live_output(session_id)
    _record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_interrupted",
        status="stopped",
        active_task=next_active_task,
    )
    _append_session_conversation_event(
        session_id,
        turn_id,
        EVENT_ASSISTANT_MESSAGE,
        status="stopped",
        payload={
            "content": assistant_text,
            "thought": live_thought,
            "toolCalls": live_tools,
            "feedbackEvents": live_feedback_events,
        },
        source="persist_interrupted_snapshot",
    )
    _append_session_conversation_event(
        session_id,
        turn_id,
        EVENT_TURN_INTERRUPTED,
        status="stopped",
        payload={
            "reason": reason or "user_stop",
            "marker": TURN_INTERRUPTED_MARKER,
            "summary": assistant_text,
        },
        source="persist_interrupted_snapshot",
    )


def _latest_assistant_message_is_stop(messages: list[dict[str, Any]]) -> bool:
    latest_messages = list(messages or [])[-1:]
    message = latest_messages[0] if latest_messages else None
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    content = str(message.get("content") or "")
    return "本轮已按请求停止" in content or "stopped as requested" in content


def _attach_turn_capture_to_result(
    result: Any,
    capture: SessionTurnCapture,
    *,
    mental_model_enabled: bool | None = None,
) -> Any:
    if not isinstance(result, dict):
        return result
    if _is_provider_failed_result(result):
        if capture.thought and not result.get("thought") and not result.get("reasoning_content"):
            result["thought"] = capture.thought
        if (
            _is_mental_model_enabled_for_turn(mental_model_enabled)
            and capture.mental_state
            and not result.get("state_info")
            and not result.get("stateInfo")
        ):
            result["state_info"] = dict(capture.mental_state)
        if capture.tool_calls and not result.get("tool_trace") and not result.get("tool_calls"):
            result["tool_trace"] = list(capture.tool_calls)
        if capture.feedback_events and not result.get("feedback_events") and not result.get("feedbackEvents"):
            result["feedback_events"] = list(capture.feedback_events)
        return result
    if capture.thought and not result.get("thought") and not result.get("reasoning_content"):
        result["thought"] = capture.thought
    visible_result = _visible_reply_candidate(result)
    if capture.content and (not visible_result or _looks_like_structured_payload(visible_result)):
        result["raw_output"] = capture.content
        result["summary"] = capture.content
    if (
        _is_mental_model_enabled_for_turn(mental_model_enabled)
        and capture.mental_state
        and not result.get("state_info")
        and not result.get("stateInfo")
    ):
        result["state_info"] = dict(capture.mental_state)
    if capture.tool_calls and not result.get("tool_trace") and not result.get("tool_calls"):
        result["tool_trace"] = list(capture.tool_calls)
    if capture.feedback_events and not result.get("feedback_events") and not result.get("feedbackEvents"):
        result["feedback_events"] = list(capture.feedback_events)
    return result


@contextmanager
def _capture_session_ui_stream(
    session_id: str,
    capture: SessionTurnCapture,
    *,
    mental_model_enabled: bool | None = None,
):
    from core.ui import get_ui

    ui = get_ui()
    _ensure_session_ui_capture_hooks(ui)
    _seed_capture_from_live_feedback_events(session_id, capture)
    event_bus = get_event_bus()
    callback_ids: list[str] = []

    def tool_event_proxy(event):
        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        if not isinstance(context, dict) or context.get("capture") is not capture:
            return
        data = event.data or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return
        status = {
            EventNames.TOOL_START: "running",
            EventNames.TOOL_SUCCESS: "done",
            EventNames.TOOL_ERROR: "failed",
        }.get(event.name, "running")
        result = data.get("result") if event.name == EventNames.TOOL_SUCCESS else ""
        error = data.get("error") if event.name == EventNames.TOOL_ERROR else ""
        summary = str(data.get("summary") or result or error or "").strip()
        capture.note_tool_event(
            name,
            status,
            summary,
            arguments=data.get("args") if isinstance(data.get("args"), dict) else None,
            result=result,
            error=error,
            duration_ms=data.get("durationMs") or data.get("duration_ms"),
            timeout_seconds=data.get("timeoutSeconds") or data.get("timeout_seconds"),
        )
        _append_session_conversation_event(
            session_id,
            capture.turn_id,
            EVENT_TOOL_CALL_STARTED if event.name == EventNames.TOOL_START else EVENT_TOOL_RESULT,
            status=status,
            payload={
                "toolCall": {
                    "name": name,
                    "status": status,
                    "arguments": data.get("args") if isinstance(data.get("args"), dict) else {},
                    "summary": summary,
                    "result": result,
                    "error": error,
                    "durationMs": data.get("durationMs") or data.get("duration_ms"),
                    "timeoutSeconds": data.get("timeoutSeconds") or data.get("timeout_seconds"),
                }
            },
            source="session_ui_capture",
        )
        _set_session_live_output(
            session_id,
            turn_id=capture.turn_id,
            tool_calls=capture.tool_calls,
            feedback_events=capture.feedback_events,
        )
        if event.name == EventNames.TOOL_ERROR:
            _record_chat_next_state_signal(
                session_id=session_id,
                turn_id=capture.turn_id,
                source="tool",
                kind="tool_error",
                polarity="negative",
                mode="evaluative",
                related_event_code="conversation.tool_error",
                summary=f"Tool failed: {name}",
                metadata={
                    "toolName": name,
                    "errorPreview": summary,
                },
            )

    def llm_status_event_proxy(event):
        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        data = event.data if isinstance(event.data, dict) else {}
        event_session_id = str(data.get("session_id") or data.get("sessionId") or "").strip()
        event_turn_id = str(data.get("turn_id") or data.get("turnId") or "").strip()
        expected_session_id = str(context.get("sessionId") or session_id or "").strip() if isinstance(context, dict) else str(session_id or "").strip()
        if event_session_id and event_session_id != expected_session_id:
            return
        if event_turn_id and capture.turn_id and event_turn_id != capture.turn_id:
            return
        if not event_session_id and (not isinstance(context, dict) or context.get("capture") is not capture):
            return
        target_session_id = event_session_id or expected_session_id
        if not target_session_id:
            return
        status = str(data.get("status") or "").strip()
        if not status:
            return
        _set_session_llm_status_live_output(
            target_session_id,
            status,
            turn_id=capture.turn_id,
            fields=data,
        )

    for event_name in (EventNames.TOOL_START, EventNames.TOOL_SUCCESS, EventNames.TOOL_ERROR):
        callback_ids.append(
            event_bus.subscribe(
                event_name,
                tool_event_proxy,
                callback_id=f"web_chat_{session_id}_{event_name}_{id(capture)}",
            )
        )
    callback_ids.append(
        event_bus.subscribe(
            EventNames.LLM_STATUS,
            llm_status_event_proxy,
            callback_id=f"web_chat_{session_id}_{EventNames.LLM_STATUS}_{id(capture)}",
        )
    )
    with llm_status_context(session_id=session_id, turn_id=capture.turn_id):
        token = _SESSION_UI_CAPTURE_CONTEXT.set(
            {
                "ui": ui,
                "sessionId": session_id,
                "capture": capture,
                "mentalModelEnabled": mental_model_enabled,
            }
        )
        try:
            yield
        finally:
            _SESSION_UI_CAPTURE_CONTEXT.reset(token)
            for callback_id in callback_ids:
                event_bus.unsubscribe_by_id(callback_id)


def _ensure_session_ui_capture_hooks(ui: Any) -> None:
    if bool(getattr(ui, "_vibelution_session_capture_wrapped", False)):
        return
    with _SESSION_UI_CAPTURE_LOCK:
        if bool(getattr(ui, "_vibelution_session_capture_wrapped", False)):
            return
        originals = {
            "stream_thought": getattr(ui, "stream_thought", None),
            "clear_thought_stream": getattr(ui, "clear_thought_stream", None),
            "stream_response": getattr(ui, "stream_response", None),
            "clear_response_stream": getattr(ui, "clear_response_stream", None),
            "set_pet_mental_state": getattr(ui, "set_pet_mental_state", None),
        }

        def active_context() -> dict[str, Any]:
            context = _SESSION_UI_CAPTURE_CONTEXT.get({})
            if not isinstance(context, dict) or context.get("ui") is not ui:
                return {}
            return context

        def stream_thought_proxy(text: str, done: bool = False):
            original = originals.get("stream_thought")
            if callable(original):
                original(text, done=done)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            cleaned = _sanitize_thought_text(text)
            if cleaned and not done:
                capture.note_thought(cleaned)
                _set_session_model_thinking_live_output(
                    session_id,
                    turn_id=capture.turn_id,
                    thought_chars=len(cleaned),
                )
                _set_session_live_output(
                    session_id,
                    turn_id=capture.turn_id,
                    thought=cleaned,
                    feedback_events=capture.feedback_events,
                )

        def clear_thought_stream_proxy():
            original = originals.get("clear_thought_stream")
            if callable(original):
                original()
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            capture.clear_thought()
            _set_session_live_output(session_id, turn_id=capture.turn_id, thought="")

        def stream_response_proxy(text: str, done: bool = False):
            original = originals.get("stream_response")
            if callable(original):
                original(text, done=done)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            cleaned = _sanitize_message_content("assistant", text)
            if cleaned:
                previous = str(capture.content or "")
                if done:
                    next_content = cleaned
                elif previous and cleaned.startswith(previous):
                    next_content = cleaned
                else:
                    next_content = f"{previous}{cleaned}" if previous else cleaned
                capture.note_content(next_content)
                _set_session_live_output(session_id, turn_id=capture.turn_id, content=next_content)

        def clear_response_stream_proxy():
            original = originals.get("clear_response_stream")
            if callable(original):
                original()
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            capture.clear_content()
            _set_session_live_output(session_id, turn_id=capture.turn_id, content="")

        def set_pet_mental_state_proxy(mood: str = "", feeling: str = "", whisper: str = ""):
            original = originals.get("set_pet_mental_state")
            if callable(original):
                original(mood=mood, feeling=feeling, whisper=whisper)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            if not _is_mental_model_enabled_for_turn(context.get("mentalModelEnabled")):
                return
            capture.note_mental_state(mood=mood, feeling=feeling, whisper=whisper)
            snapshot = _live_mental_snapshot(capture.mental_state, get_web_language())
            if snapshot is not None:
                _set_session_live_output(
                    session_id,
                    turn_id=capture.turn_id,
                    mental_snapshot=snapshot,
                    feedback_events=capture.feedback_events,
                )

        setattr(ui, "_vibelution_session_capture_originals", originals)
        setattr(ui, "stream_thought", stream_thought_proxy)
        setattr(ui, "clear_thought_stream", clear_thought_stream_proxy)
        setattr(ui, "stream_response", stream_response_proxy)
        setattr(ui, "clear_response_stream", clear_response_stream_proxy)
        setattr(ui, "set_pet_mental_state", set_pet_mental_state_proxy)
        setattr(ui, "_vibelution_session_capture_wrapped", True)


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


def _record_child_session_event(
    phase: str,
    *,
    parent_session_id: str,
    child_session_id: str,
    fields: dict[str, Any] | None = None,
    outcome: str = "recorded",
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            f"child_session_{phase}",
            f"conversation.child.{phase}",
            level="info",
            outcome=outcome,
            message="Conversation child-session event.",
            fields={
                "parentSessionId": str(parent_session_id or "").strip(),
                "childSessionId": str(child_session_id or "").strip(),
                **(fields or {}),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(parent_session_id)}-children.jsonl",
            child_log_payload={
                "parentSessionId": str(parent_session_id or "").strip(),
                "childSessionId": str(child_session_id or "").strip(),
                "phase": str(phase or "").strip(),
                "createdAt": _now_timestamp(),
                **(fields or {}),
            },
            lifecycle=True,
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


def _build_stopped_turn_result(reason: str) -> dict[str, Any]:
    return {
        "status": "stopped",
        "summary": "",
        "raw_output": "",
        "stop_requested": True,
        "stop_reason": str(reason or "").strip(),
        "tool_call_count": 0,
        "tool_trace": [],
    }


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
        messages = normalize_chat_messages(conversation.get("messages") or [])
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


def _looks_like_agent_inbox_protocol_message(text: Any) -> bool:
    value = str(text or "").lstrip()
    if not value:
        return False
    return value.startswith("[Agent 私信]") or value.startswith("[Agent 私信回复]")


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
    if outcome in {"done", "blocked", "needs_input"}:
        return True
    if explicit_outcome == "progress":
        return False
    if not visible and (tool_count > 0 or tool_trace):
        return False
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


def _visible_reply_summary_candidate(result: dict[str, Any]) -> str:
    visible = _visible_reply_candidate(result)
    if visible and _looks_like_provider_error_text(visible):
        return _user_visible_failure_summary(visible, lang=get_web_language())
    if visible and not _looks_like_structured_payload(visible):
        return visible
    reply = _format_visible_reply(result)
    if reply and _NO_VISIBLE_REPLY_ZH not in reply and _NO_VISIBLE_REPLY_EN not in reply:
        return reply
    return ""


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
    metadata.pop("continuation_limit_reached", None)
    result["metadata"] = metadata
    return result


def _build_auto_continue_paused_result(
    result: Any,
    visible_result: dict[str, Any] | None,
    turn_count: int,
) -> Any:
    if not isinstance(result, dict):
        return result
    merged = _merge_continuation_visible_result(dict(result), visible_result)
    visible = _visible_reply_summary_candidate(merged) if isinstance(merged, dict) else ""
    if not visible:
        visible = "本轮已完成阶段性处理，等待你的下一条消息继续。"
    paused = dict(merged)
    metadata = dict(paused.get("metadata") or {}) if isinstance(paused.get("metadata"), dict) else {}
    metadata.update(
        {
            "continuation_turn_count": turn_count,
            "internal_auto_continue_blocked": True,
            "continuation_pause_reason": "internal_auto_continue_not_authorized",
        }
    )
    paused["metadata"] = metadata
    paused["status"] = "completed"
    paused["outcome"] = "needs_input"
    paused["task_outcome"] = "needs_input"
    paused["summary"] = visible
    paused["raw_output"] = visible
    return paused


def _chat_turn_result_status(result_status: str, result: Any, *, stop_requested: bool) -> str:
    if stop_requested:
        return "stopped_by_user"
    normalized = str(result_status or "").strip().lower()
    metadata = dict(result.get("metadata") or {}) if isinstance(result, dict) and isinstance(result.get("metadata"), dict) else {}
    if isinstance(result, dict):
        contract = build_chat_coding_result_contract(result)
        outcome = str(contract.get("outcome") or result.get("outcome") or result.get("task_outcome") or "").strip().lower()
        explicit_outcome = _explicit_chat_result_outcome(result)
        visible = _visible_reply_candidate(result)
        if (
            normalized == "completed"
            and explicit_outcome != "progress"
            and visible
            and (has_conclusion_signal(visible) or has_next_action_signal(visible))
        ):
            return "completed"
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
    next_action = ""
    if isinstance(latest_result, dict):
        contract = build_chat_coding_result_contract(latest_result)
        next_action = trim_lines(
            contract.get("next_action") or latest_result.get("recommended_next_action") or "",
            max_lines=2,
        )
    goal = _unwrap_continuation_goal(effective_prompt or original_prompt)
    if _is_continue_request(goal):
        goal = _unwrap_continuation_goal(_latest_effective_user_message(history_messages) or original_prompt)
    lines = [
        f"继续完成同一个用户目标：{goal}",
        f"上一内部回合仍未完成用户目标（第 {turn_index} 轮）。",
        "不要只输出 <state>；如果目标已完成，请给出可见汇报并标记 outcome=done。",
    ]
    if next_action:
        lines.append(f"优先执行上一轮下一步：{next_action}")
    guidance_lines = [item for item in list(guidance_summaries or []) if str(item or "").strip()]
    if guidance_lines:
        lines.append("用户在当前运行轮补充了以下引导，请在不违背安全边界的前提下优先对齐：")
        for item in guidance_lines[:3]:
            lines.append(f"- {item}")
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


def _build_session_active_task(
    session_id: str,
    result: Any,
    messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
    user_message_source: str = "",
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return existing_task if _is_task_tool_backed_active_task(existing_task) else None

    task_tool_called = _result_has_task_context_tool(result)
    existing_task_tool_backed = _is_task_tool_backed_active_task(existing_task)
    if not task_tool_called and not existing_task_tool_backed:
        return None

    contract = build_chat_coding_result_contract(result)
    read_files = _normalize_project_paths(contract.get("read_files") or [], existing_only=True)
    changed_files = _normalize_project_paths(contract.get("changed_files") or [], existing_only=False)
    if isinstance(existing_task, dict):
        if not read_files:
            read_files = _normalize_project_paths(existing_task.get("read_files") or [], existing_only=True)
        if not changed_files:
            changed_files = _normalize_project_paths(existing_task.get("changed_files") or [], existing_only=False)
    verification_status = str(contract.get("verification_status") or "").strip().lower()
    verification_summary = trim_lines(contract.get("verification_summary") or "", max_lines=4)
    blocked_reason = trim_lines(contract.get("blocked_reason") or "", max_lines=3)
    required_user_input = trim_lines(contract.get("required_user_input") or "", max_lines=3)
    next_action = trim_lines(contract.get("next_action") or "", max_lines=3)
    latest_summary = trim_lines(
        _visible_reply_summary_candidate(result),
        max_lines=6,
    )

    if not any(
        (
            read_files,
            changed_files,
            verification_status,
            verification_summary,
            blocked_reason,
            required_user_input,
            next_action,
            latest_summary,
        )
    ):
        return existing_task

    preview_tabs = _merge_project_paths(
        _normalize_project_paths(changed_files, existing_only=True),
        read_files,
    )
    default_file_context = (
        changed_files[-1] if changed_files else ""
    ) or (read_files[-1] if read_files else "")
    active_preview_path = (
        _normalize_project_path(default_file_context, existing_only=True)
        or (preview_tabs[0] if preview_tabs else "")
        or "agent"
    )
    if active_preview_path != "agent" and active_preview_path not in preview_tabs:
        preview_tabs = [active_preview_path, *preview_tabs]

    outcome = str(contract.get("outcome") or "").strip().lower()
    task_status = _task_status_from_result_contract(
        outcome,
        read_files=read_files,
        changed_files=changed_files,
        verification_status=verification_status,
    )
    raw_last_user_message = _latest_user_message(messages)
    last_user_message = _latest_real_user_message(messages) or raw_last_user_message
    existing_metadata = dict(existing_task.get("metadata") or {}) if isinstance(existing_task, dict) else {}
    existing_created_at = str(existing_task.get("created_at") or "").strip() if isinstance(existing_task, dict) else ""
    existing_turn_count = (
        _coerce_nonnegative_int(existing_task.get("turn_count") or 0) if isinstance(existing_task, dict) else 0
    )
    existing_goal = (
        trim_lines(existing_task.get("goal") or existing_task.get("title") or "", max_lines=2)
        if isinstance(existing_task, dict)
        else ""
    )
    history_goal = _latest_effective_user_message(messages)
    last_is_contextual_confirmation = _is_contextual_confirmation_message(last_user_message)
    if _is_continue_request(last_user_message) or last_is_contextual_confirmation:
        effective_goal = existing_goal if existing_goal and _is_effective_user_message(existing_goal) else history_goal
        history_goal_index = _latest_effective_user_message_with_index(messages)[1]
        if _should_prefer_history_goal_over_active_task(
            existing_task,
            messages,
            existing_goal=existing_goal,
            history_goal=history_goal,
            history_goal_index=history_goal_index,
        ):
            effective_goal = history_goal
    else:
        effective_goal = last_user_message if _is_effective_user_message(last_user_message) else history_goal
    if not effective_goal:
        effective_goal = existing_goal if existing_goal and _is_effective_user_message(existing_goal) else history_goal
    effective_title = (
        effective_goal
        if (_is_continue_request(last_user_message) or last_is_contextual_confirmation) and effective_goal
        else (last_user_message if _is_effective_user_message(last_user_message) else (effective_goal or latest_summary))
    )
    metadata = dict(existing_metadata)
    metadata.update(
        {
            "source": "task_tool",
            "outcome": outcome,
            "default_file_context": default_file_context,
            "active_preview_path": active_preview_path,
        }
    )
    if blocked_reason:
        metadata["blocked_reason"] = blocked_reason
    if required_user_input:
        metadata["required_user_input"] = required_user_input
    if str(user_message_source or "").strip() == "agent_inbox":
        metadata["last_user_message_filtered"] = True
        metadata["last_user_message_reason"] = "agent_inbox_message"
    elif raw_last_user_message and raw_last_user_message != last_user_message:
        metadata["last_user_message_filtered"] = True
        metadata["last_user_message_reason"] = "agent_inbox_message"

    return {
        "task_id": str(existing_task.get("task_id") or f"{session_id}-coding-task").strip()
        if isinstance(existing_task, dict)
        else f"{session_id}-coding-task",
        "kind": "coding",
        "status": task_status,
        "title": trim_lines(effective_title, max_lines=2),
        "goal": trim_lines(effective_goal, max_lines=2),
        "read_files": read_files,
        "changed_files": changed_files,
        "verification_status": verification_status,
        "verification_summary": verification_summary,
        "latest_summary": latest_summary,
        "next_action": next_action or required_user_input or blocked_reason,
        "last_user_message": last_user_message,
        "turn_count": max(0, existing_turn_count) + 1,
        "resume_count": (
            _coerce_nonnegative_int(existing_task.get("resume_count") or 0)
            if isinstance(existing_task, dict)
            else 0
        ),
        "created_at": existing_created_at or _now_timestamp(),
        "updated_at": _now_timestamp(),
        "default_file_context": default_file_context,
        "preview_tabs": preview_tabs,
        "active_preview_path": active_preview_path,
        "metadata": metadata,
    }


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


def _register_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = _SESSION_STREAM_SUBSCRIBERS.setdefault(session_id, set())
        bucket.add(subscriber)


def _unregister_session_stream_subscriber(session_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        bucket = _SESSION_STREAM_SUBSCRIBERS.get(session_id)
        if not bucket:
            return
        bucket.discard(subscriber)
        if not bucket:
            _SESSION_STREAM_SUBSCRIBERS.pop(session_id, None)


def _publish_session_detail_snapshot(session_id: str, *, detail: dict[str, Any] | None = None) -> None:
    started_at = _perf_counter()
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    if not subscribers:
        return
    detail = detail if detail is not None else get_session_detail(session_id)
    if detail is None:
        return
    current_phase = str(detail.get("currentPhase") or detail.get("status") or "") if isinstance(detail, dict) else ""
    normalized_phase = current_phase.strip().lower()
    is_busy_snapshot = normalized_phase in _SESSION_STREAM_BUSY_PHASES
    interval_seconds = _SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS
    now = _perf_counter()
    should_throttle = False
    if is_busy_snapshot:
        with _SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            last_snapshot_at = _SESSION_STREAM_LAST_SNAPSHOT_AT.get(session_id, 0.0)
            if last_snapshot_at and now - last_snapshot_at < interval_seconds:
                should_throttle = True
                skipped_count = _SESSION_STREAM_THROTTLED_COUNTS.get(session_id, 0) + 1
                _SESSION_STREAM_THROTTLED_COUNTS[session_id] = skipped_count
                _SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = last_snapshot_at
            else:
                skipped_count = _SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
                _SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
        if should_throttle:
            if skipped_count % 10 == 1:
                _record_session_detail_snapshot_throttled_event(
                    session_id=session_id,
                    subscriber_count=len(subscribers),
                    skipped_count=skipped_count,
                    current_phase=current_phase,
                    interval_ms=int(round(interval_seconds * 1000)),
                )
            return
        if skipped_count:
            _record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    else:
        with _SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            _SESSION_STREAM_LAST_SNAPSHOT_AT[session_id] = now
            skipped_count = _SESSION_STREAM_THROTTLED_COUNTS.pop(session_id, 0)
        if skipped_count:
            _record_session_detail_snapshot_throttled_event(
                session_id=session_id,
                subscriber_count=len(subscribers),
                skipped_count=skipped_count,
                current_phase=current_phase,
                interval_ms=int(round(interval_seconds * 1000)),
            )
    event = {
        "type": "session_detail",
        "sessionId": session_id,
        "ledgerSeq": _coerce_nonnegative_int(detail.get("ledgerSeq") or 0) if isinstance(detail, dict) else 0,
        "detail": detail,
    }
    delivered_count = 0
    dropped_count = 0
    for subscriber in subscribers:
        dropped_count += _coalesce_session_stream_queue(subscriber, event_type="session_detail")
        try:
            subscriber.put_nowait(event)
            delivered_count += 1
        except queue.Full:
            try:
                subscriber.get_nowait()
                dropped_count += 1
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
                delivered_count += 1
            except queue.Full:
                dropped_count += 1
                continue
    _record_session_detail_snapshot_published_event(
        session_id=session_id,
        elapsed_ms=_elapsed_ms(started_at),
        subscriber_count=len(subscribers),
        delivered_count=delivered_count,
        dropped_count=dropped_count,
        message_count=len(detail.get("messages") or []) if isinstance(detail, dict) else 0,
        current_phase=current_phase,
    )


def _publish_session_assistant_delta(
    session_id: str,
    state: SessionLiveOutputState,
    *,
    done: bool = False,
) -> None:
    started_at = _perf_counter()
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    if not subscribers:
        return
    event = {
        "type": "assistant_delta",
        "sessionId": session_id,
        "turnId": str(state.turn_id or "").strip(),
        "ledgerSeq": _session_ledger_sequence(session_id),
        "stage": str(state.stage or "").strip(),
        "content": str(state.content or ""),
        "thought": str(state.thought or ""),
        "contentDelta": str(state.content_delta or ""),
        "thoughtDelta": str(state.thought_delta or ""),
        "replaceContent": bool(state.replace_content),
        "replaceThought": bool(state.replace_thought),
        "feedbackEvents": list(state.feedback_events or []),
        "updatedAt": str(state.updated_at or "").strip() or _now_timestamp(),
        "done": bool(done),
    }
    delivered_count = 0
    dropped_count = 0
    for subscriber in subscribers:
        dropped_count += _coalesce_session_stream_queue(
            subscriber,
            event_type="assistant_delta",
            replacement_event=event,
        )
        try:
            subscriber.put_nowait(event)
            delivered_count += 1
        except queue.Full:
            try:
                subscriber.get_nowait()
                dropped_count += 1
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
                delivered_count += 1
            except queue.Full:
                dropped_count += 1
                continue
    _record_session_assistant_delta_published_event(
        session_id=session_id,
        turn_id=str(state.turn_id or "").strip(),
        stage=str(state.stage or "").strip(),
        elapsed_ms=_elapsed_ms(started_at),
        subscriber_count=len(subscribers),
        delivered_count=delivered_count,
        dropped_count=dropped_count,
        content_chars=len(str(state.content_delta or "")),
        thought_chars=len(str(state.thought_delta or "")),
        done=done,
    )


def _coalesce_session_stream_queue(
    subscriber: queue.Queue[dict[str, Any]],
    *,
    event_type: str,
    replacement_event: dict[str, Any] | None = None,
) -> int:
    """Drop stale status snapshots for one SSE subscriber before enqueuing a newer one."""

    normalized_event_type = str(event_type or "").strip()
    if normalized_event_type not in _SESSION_STREAM_COALESCED_EVENT_TYPES:
        return 0
    kept: list[dict[str, Any]] = []
    dropped_count = 0
    while True:
        try:
            existing = subscriber.get_nowait()
        except queue.Empty:
            break
        if str(existing.get("type") or "").strip() == normalized_event_type:
            if normalized_event_type == "assistant_delta" and replacement_event is not None:
                if _merge_assistant_delta_stream_events(existing, replacement_event):
                    dropped_count += 1
                    continue
                kept.append(existing)
                continue
            dropped_count += 1
            continue
        kept.append(existing)
    for existing in kept:
        try:
            subscriber.put_nowait(existing)
        except queue.Full:
            dropped_count += 1
    return dropped_count


def _merge_assistant_delta_stream_events(existing: dict[str, Any], replacement: dict[str, Any]) -> bool:
    if str(existing.get("sessionId") or "") != str(replacement.get("sessionId") or ""):
        return False
    if str(existing.get("turnId") or "") != str(replacement.get("turnId") or ""):
        return False
    for field_name, delta_key, replace_key in (
        ("content", "contentDelta", "replaceContent"),
        ("thought", "thoughtDelta", "replaceThought"),
    ):
        existing_delta = str(existing.get(delta_key) if existing.get(delta_key) is not None else existing.get(field_name) or "")
        replacement_delta = str(
            replacement.get(delta_key) if replacement.get(delta_key) is not None else replacement.get(field_name) or ""
        )
        if bool(replacement.get(replace_key)):
            replacement[delta_key] = replacement_delta
            replacement[replace_key] = True
            continue
        if bool(existing.get(replace_key)):
            replacement[delta_key] = existing_delta + replacement_delta
            replacement[replace_key] = True
            continue
        replacement[delta_key] = existing_delta + replacement_delta
        replacement[replace_key] = False
    if not replacement.get("stage"):
        replacement["stage"] = str(existing.get("stage") or "")
    if "feedbackEvents" not in replacement and "feedbackEvents" in existing:
        replacement["feedbackEvents"] = list(existing.get("feedbackEvents") or [])
    return True


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"
