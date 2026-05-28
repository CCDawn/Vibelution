"""Real chat session payloads for the web workbench."""

from __future__ import annotations

import base64
import binascii
import copy
import json
import queue
import re
import secrets
import threading
import hashlib
import time
from collections import deque
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
from core.chat.chat_result_contract import build_chat_coding_result_contract
from core.chat.chat_result_formatter import format_chat_reply
from core.chat.chat_task_types import trim_lines
from core.chat.skill_registry import build_skill_runtime_context, skill_descriptor_for_log
from core.chat.slash_commands import SkillSlashCommand, parse_skill_slash_command
from core.infrastructure.event_bus import EventNames, get_event_bus
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
)
from core.runtime_manager.work_run_store import WorkRunStore
from core.ui.chat_state import (
    CHAT_STATE_VERSION,
    DEFAULT_CHAT_CONVERSATION_ID,
    DEFAULT_CHAT_CONVERSATION_TITLE,
    load_chat_state,
    normalize_chat_attachments,
    normalize_chat_messages,
    normalize_chat_tool_calls,
    save_chat_state,
)

from . import agent_directory_service
from .i18n import get_web_language, text_for
from .agent_directory_service import (
    AgentNotFoundError,
    active_agent_runtime,
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
_CHAT_STATE_LOCK = threading.Lock()
_RUNNING_SESSIONS_LOCK = threading.Lock()
_RUNNING_SESSION_IDS: set[str] = set()
_SESSION_ACTIVE_TURN_IDS: dict[str, str] = {}
_SESSION_ACTIVE_TURN_LEASES: dict[str, list[str]] = {}
_SESSION_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="web-chat-turn")
_SESSION_AGENT_SCHEDULER_LOCK = threading.Lock()
_SESSION_AGENT_SCHEDULER_CONDITION = threading.Condition(_SESSION_AGENT_SCHEDULER_LOCK)
_SESSION_AGENT_ACTIVE_TURN_IDS: dict[str, str] = {}
_SESSION_AGENT_QUEUES: dict[str, deque[dict[str, Any]]] = {}
_SESSION_STREAM_SUBSCRIBERS_LOCK = threading.Lock()
_SESSION_STREAM_SUBSCRIBERS: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
_SESSION_STREAM_HEARTBEAT_SECONDS = 15.0
_SESSION_STREAM_QUEUE_SIZE = 8
_SESSION_TURN_CONTROLS_LOCK = threading.Lock()
_SESSION_TURN_CONTROLS: dict[str, "SessionTurnControl"] = {}
_SESSION_LIVE_OUTPUTS_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUTS: dict[str, "SessionLiveOutputState"] = {}
_SESSION_UI_CAPTURE_LOCK = threading.Lock()
_SESSION_UI_CAPTURE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_session_ui_capture_context",
    default={},
)
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
_SESSION_IMAGE_ARTIFACT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
_SESSION_USER_IMAGE_MAX_BYTES = 8 * 1024 * 1024
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
_IMAGE_ATTACHMENT_IMAGE2_PATTERNS = (
    "生成",
    "画一张",
    "帮我画",
    "画成",
    "绘制",
    "重绘",
    "改成",
    "改为",
    "修改",
    "调整",
    "优化",
    "美化",
    "更好看",
    "换风格",
    "风格",
    "做头像",
    "头像",
    "海报",
    "参考",
    "基于",
    "照着",
    "2d",
    "卡通",
    "动画",
    "二次元",
    "create",
    "generate",
    "draw",
    "redraw",
    "edit",
    "style",
    "restyle",
    "make",
    "poster",
    "avatar",
    "reference",
)
_VISION_MODEL_NAME_HINTS = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5.5",
    "gpt-5o",
    "vision",
    "vl",
    "qwen-vl",
    "qvq",
    "gemini",
    "claude-3",
    "claude-4",
    "glm-4v",
    "multimodal",
    "omni",
)
_SESSION_USER_IMAGE_MAX_ATTACHMENTS_PER_TURN = 4
DEFAULT_SESSION_AGENT_PROFILE_ID = "primary"


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


def _session_workspace_relative_path(session_id: str) -> str:
    return f"workspace/sessions/{_safe_session_workspace_token(session_id)}"


def _ensure_session_workspace(session_id: str) -> Path:
    sessions_root = (PROJECT_ROOT / "workspace" / "sessions").resolve()
    workspace_path = (PROJECT_ROOT / _session_workspace_relative_path(session_id)).resolve()
    if not workspace_path.is_relative_to(sessions_root):
        raise SessionValidationError(f"Invalid session workspace path: {workspace_path}")
    workspace_path.mkdir(parents=True, exist_ok=True)
    for subdir in _SESSION_WORKSPACE_SUBDIRS:
        (workspace_path / subdir).mkdir(parents=True, exist_ok=True)
    return workspace_path


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

    sessions_root = (PROJECT_ROOT / "workspace" / "sessions").resolve()
    workspace_path = (PROJECT_ROOT / _session_workspace_relative_path(normalized_session_id)).resolve()
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


def _repair_conversation_agent_profile_from_instance(
    conversation: dict[str, Any],
    *,
    conversation_id: str,
    agent_id: str,
    agent: dict[str, Any],
    agent_profile_id: str,
) -> bool:
    previous_profile_id = _normalize_session_agent_profile_id(
        conversation.get("agent_profile_id")
        or conversation.get("agentProfileId")
        or DEFAULT_SESSION_AGENT_PROFILE_ID
    )
    changed = False
    if "agent_profile_id" in conversation:
        conversation.pop("agent_profile_id", None)
        changed = True
    if "agentProfileId" in conversation:
        conversation.pop("agentProfileId", None)
        changed = True
    if changed:
        _record_session_agent_profile_repaired_event(
            conversation_id,
            agent_id=agent_id,
            previous_profile_id=previous_profile_id,
            profile_id=agent_profile_id,
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
    existing_agent = _agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
    agent_profile_id = _normalize_session_agent_profile_id(
        (existing_agent or {}).get("profileId")
        or conversation.get("agent_profile_id")
        or conversation.get("agentProfileId")
        or DEFAULT_SESSION_AGENT_PROFILE_ID
    )
    default_primary_mode = agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE
    primary_mode = str((existing_agent or {}).get("primaryMode") or default_primary_mode).strip() or default_primary_mode
    role_key = str((existing_agent or {}).get("roleKey") or "").strip()
    prompt_template_id = str((existing_agent or {}).get("promptTemplateId") or "").strip()
    if existing_agent_id and not existing_agent:
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
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
        changed = _repair_conversation_agent_profile_from_instance(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
            agent_profile_id=agent_profile_id,
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
        changed = _repair_conversation_agent_profile_from_instance(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
            agent_profile_id=agent_profile_id,
        ) or changed
        return changed
    agent = ensure_agent_for_session(
        conversation_id,
        display_name=title,
        profile_id=agent_profile_id,
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
    agent_profile_id = _normalize_session_agent_profile_id(agent.get("profileId") or agent_profile_id)
    changed = _repair_conversation_agent_profile_from_instance(
        conversation,
        conversation_id=conversation_id,
        agent_id=agent_id,
        agent=agent,
        agent_profile_id=agent_profile_id,
    ) or changed
    return changed


def _sync_agent_directory_project_root() -> None:
    if agent_directory_service.PROJECT_ROOT != PROJECT_ROOT:
        agent_directory_service.PROJECT_ROOT = PROJECT_ROOT


def _agent_lookup_for_conversations() -> dict[str, dict[str, Any]]:
    _sync_agent_directory_project_root()
    state = agent_directory_service.repair_agent_directory()
    return {
        str(item.get("agentId") or "").strip(): item
        for item in state.get("agents") or []
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    }


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


def _session_agent_status_payload(
    agent_id: str,
    agent: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
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


def _session_agent_visible_in_indexes(summary: dict[str, Any]) -> bool:
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
            }


@dataclass
class SessionLiveOutputState:
    """Ephemeral live assistant output for one active web chat turn."""

    session_id: str
    turn_id: str = ""
    stage: str = ""
    thought: str = ""
    content: str = ""
    mental_snapshot: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = ""


@dataclass
class SessionTurnCapture:
    """Collect live UI breadcrumbs so the web session can replay them."""

    session_id: str
    turn_id: str = ""
    thought: str = ""
    content: str = ""
    mental_state: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def note_thought(self, text: str) -> None:
        cleaned = _sanitize_thought_text(text)
        if cleaned:
            self.thought = cleaned

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
        for index in range(len(self.tool_calls) - 1, -1, -1):
            existing = self.tool_calls[index]
            if existing.get("name") == tool_name and existing.get("status") == "running":
                self.tool_calls[index] = entry
                return
        self.tool_calls.append(entry)
        if len(self.tool_calls) > 30:
            self.tool_calls = self.tool_calls[-30:]


def list_sessions() -> list[dict]:
    """Return summarized sessions sourced from persisted chat state."""

    active_id, conversations = _load_conversations()
    conversations = _append_agent_directory_conversations(conversations)
    sessions = []
    for item in conversations:
        summary = _build_session_summary(item)
        if _session_agent_visible_in_indexes(summary):
            sessions.append(summary)
        else:
            _record_session_agent_missing_index_event(summary, source="list_sessions")
    sessions.sort(
        key=lambda item: (
            0 if item["id"] == active_id else 1,
            -_timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
        )
    )
    return sessions


def get_session_detail(session_id: str) -> dict | None:
    """Return a session detail payload by persisted conversation id."""

    _ensure_agent_directory_conversation_materialized(session_id, source="get_session_detail")
    _, conversations = _load_conversations()
    conversations = _append_agent_directory_conversations(conversations)
    for item in conversations:
        if item["id"] == session_id:
            return _build_session_detail(item)
    return None


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


def create_chat_session(
    *,
    title: str = "",
    profile_id: str | None = None,
    created_by: str = "user",
) -> dict:
    """Create a new empty chat session and make it active."""

    lang = get_web_language()
    normalized_agent_profile_id = _normalize_session_agent_profile_id(profile_id or DEFAULT_SESSION_AGENT_PROFILE_ID)
    _validate_session_agent_profile_id(normalized_agent_profile_id, lang=lang)
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
            profile_id=normalized_agent_profile_id,
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
    return get_session_detail(session_id) or {}


def list_session_agent_templates() -> list[dict[str, Any]]:
    """Return LLM-backed agent templates that a chat session can bind to."""

    lang = get_web_language()
    config = get_config()
    templates: list[dict[str, Any]] = []
    for profile_id in sorted(config.llm.profiles):
        profile = config.llm.get_profile(profile_id=profile_id)
        provider = config.llm.get_provider(profile.provider_id)
        api_key_configured = bool(config.get_api_key_for_profile(profile_id=profile_id))
        requires_api_key = bool(getattr(provider, "requires_api_key", False))
        templates.append(
            {
                "templateId": str(profile_id),
                "profileId": str(profile_id),
                "label": _session_agent_profile_label(str(profile_id), lang),
                "model": str(profile.model or ""),
                "providerKind": str(provider.kind or ""),
                "apiKeyConfigured": api_key_configured or not requires_api_key,
                "requiresApiKey": requires_api_key,
                "missingApiKey": requires_api_key and not api_key_configured,
            }
        )
    return templates


def update_chat_session(
    session_id: str,
    *,
    title: str | None = None,
    agent_id: str | None = None,
    profile_id: str | None = None,
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

    normalized_agent_profile_id: str | None = None
    if profile_id is not None:
        normalized_agent_profile_id = _normalize_session_agent_profile_id(profile_id)
        _validate_session_agent_profile_id(normalized_agent_profile_id, lang=lang)
    normalized_agent_id: str | None = None
    selected_agent: dict[str, Any] | None = None
    if agent_id is not None:
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id:
            raise SessionValidationError(text_for(lang, zh="请选择会话 Agent。", en="Choose a session Agent."))
        selected_agent = get_agent(normalized_agent_id, include_archived=False)
        if not selected_agent:
            raise SessionValidationError(text_for(lang, zh=f"未找到会话 Agent：{normalized_agent_id}", en=f"Session Agent not found: {normalized_agent_id}"))
        _validate_session_agent_profile_id(
            _normalize_session_agent_profile_id(selected_agent.get("profileId") or DEFAULT_SESSION_AGENT_PROFILE_ID),
            lang=lang,
        )

    with _CHAT_STATE_LOCK:
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _find_conversation_entry(payload, conversation_id)
        if conversation is None:
            raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
        _ensure_conversation_workspace_metadata(conversation)
        _ensure_conversation_agent_metadata(conversation)

        if normalized_title is not None:
            conversation["title"] = normalized_title
        if selected_agent is not None and normalized_agent_id is not None:
            _bind_conversation_to_agent_instance(
                conversation,
                selected_agent,
                session_id=conversation_id,
                source="agent_id",
            )
        elif normalized_agent_profile_id is not None:
            _update_conversation_agent_profile(
                conversation,
                normalized_agent_profile_id,
                session_id=conversation_id,
            )
        _ensure_conversation_agent_metadata(conversation)
        payload["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)

    _publish_session_detail_snapshot(conversation_id)
    return get_session_detail(conversation_id) or {}


def update_chat_session_title(session_id: str, title: str) -> dict:
    """Persist a user-facing chat session title."""

    return update_chat_session(session_id, title=title)


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
    agent_profile_id = _normalize_session_agent_profile_id(agent.get("profileId") or DEFAULT_SESSION_AGENT_PROFILE_ID)
    conversation["agent_id"] = agent_id
    conversation["agentId"] = agent_id
    _repair_conversation_agent_profile_from_instance(
        conversation,
        conversation_id=session_id,
        agent_id=agent_id,
        agent=agent,
        agent_profile_id=agent_profile_id,
    )
    try:
        if str(agent.get("directSessionId") or "").strip() != str(session_id or "").strip():
            update_agent_instance(agent_id, status="active", metadata={"previousDirectSessionId": str(agent.get("directSessionId") or "").strip()})
            agent_directory_service.ensure_agent_for_session(
                session_id,
                display_name=str(agent.get("displayName") or conversation.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE),
                profile_id=agent_profile_id,
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
        profile_id=agent_profile_id,
        source=source,
        prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
        role_key=str(agent.get("roleKey") or "").strip(),
    )


def _update_conversation_agent_profile(
    conversation: dict[str, Any],
    profile_id: str,
    *,
    session_id: str,
) -> None:
    normalized_profile_id = _normalize_session_agent_profile_id(profile_id)
    existing_agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    existing_agent = get_agent(existing_agent_id) if existing_agent_id else None
    if existing_agent:
        update_agent_instance(existing_agent_id, profile_id=normalized_profile_id)
    conversation.pop("agent_profile_id", None)
    conversation.pop("agentProfileId", None)
    _record_session_agent_binding_updated_event(
        session_id,
        agent_id=existing_agent_id,
        profile_id=normalized_profile_id,
        source="profile_id_request",
        prompt_template_id=str((existing_agent or {}).get("promptTemplateId") or "").strip(),
        role_key=str((existing_agent or {}).get("roleKey") or "").strip(),
    )


def delete_chat_session(session_id: str) -> dict:
    """Delete one chat session and return the next active session detail."""

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

        normalized_target = _normalize_conversation(target_conversation) or {}
        if _is_session_busy_for_delete(conversation_id, normalized_target):
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
            remaining = [
                _make_empty_conversation(
                    next_active_id,
                    title=text_for(lang, zh="新会话", en="New session"),
                    timestamp=now,
                )
            ]

        now = _now_timestamp()
        payload["version"] = int(payload.get("version") or CHAT_STATE_VERSION)
        payload["active_conversation_id"] = next_active_id
        payload["updated_at"] = now
        payload["conversations"] = remaining
        save_chat_state(PROJECT_ROOT, payload)

    _set_session_running(conversation_id, False)
    _clear_session_turn_control(conversation_id)
    _clear_session_live_output(conversation_id)
    return get_session_detail(next_active_id) or {}


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
    _clear_session_turn_control(conversation_id, turn_id=controller.turn_id)
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
    turn_mode: str = "",
    write_intent: bool | None = None,
    message_metadata: dict[str, Any] | None = None,
    message_source: str = "raw",
    include_started_turn_id: bool = False,
) -> dict:
    """Persist a user message and start a single web chat turn."""

    lang = get_web_language()
    conversation_id = str(session_id or "").strip()
    message = _resolve_user_message_content(content, content_utf8_base64=content_utf8_base64)
    if not conversation_id:
        raise SessionNotFoundError(text_for(lang, zh="未找到当前会话。", en="Session not found."))
    _validate_user_message_not_encoding_replacement(message, lang=lang)
    with _CHAT_STATE_LOCK:
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
        if not message and not attachments:
            raise SessionValidationError(
                text_for(lang, zh="请输入本轮消息或添加图片后再发送。", en="Enter a message or attach an image before sending.")
            )

        if _is_session_running(conversation_id):
            raise SessionBusyError(
                text_for(
                    lang,
                    zh="当前会话仍在运行，请等这一轮结束后再继续发送。",
                    en="This session is still running. Wait for the current turn to finish before sending again.",
                )
            )

        active_task = _normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
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
            raise SessionBusyError(_localize_lease_conflict(lease_decision.reason, lang=lang))

        _ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        agent_profile_id = _normalize_session_agent_profile_id(
            (agent or {}).get("profileId")
            or conversation.get("agent_profile_id")
            or conversation.get("agentProfileId")
            or DEFAULT_SESSION_AGENT_PROFILE_ID
        )
        previous_messages = normalize_chat_messages(conversation.get("messages") or [])
        skill_command = parse_skill_slash_command(message)
        skill_invocation = _skill_invocation_payload(skill_command) if skill_command is not None else None
        turn_control = _create_session_turn_control(conversation_id)
        persisted_message_metadata = dict(message_metadata or {}) if isinstance(message_metadata, dict) else {}
        if persisted_message_metadata:
            persisted_message_metadata.setdefault("turnId", turn_control.turn_id)
        if skill_invocation:
            persisted_message_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
        user_entry = _make_chat_message(
            "user",
            message,
            metadata=persisted_message_metadata,
            attachments=attachments,
        )
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
        user_message_source=str(message_source or "raw").strip() or "raw",
        attachments=attachments,
    )
    _publish_session_detail_snapshot(conversation_id)

    normalized_message_source = str(message_source or "").strip() or "raw"
    if attachments and normalized_message_source != "agent_inbox":
        image_route = _resolve_image_attachment_turn_route(message, agent_profile_id=agent_profile_id)
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
                agent_profile_id=agent_profile_id,
                agent_id=agent_id,
                attachments=attachments,
                leases=requested_leases,
                raw_user_message=message,
            )
            detail = get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail
        if image_route["route"] == "block_vision":
            visible = _image_input_unsupported_message(lang, profile_id=agent_profile_id)
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
                agent_profile_id=agent_profile_id,
                agent_id=agent_id,
                attachments=attachments,
                leases=requested_leases,
                raw_user_message=message,
                outcome="blocked",
                level="warning",
            )
            detail = get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail
        if image_route["route"] == "image2":
            context = {
                "session_id": conversation_id,
                "turn_id": turn_control.turn_id,
                "turn_control": turn_control,
                "user_message": message or _image2_prompt_from_attachments(lang),
                "raw_user_message": message,
                "user_message_source": "image_attachment_image2",
                "attachments": attachments,
                "history_messages": previous_messages,
                "mental_model_enabled": mental_model_enabled,
                "active_task": active_task,
                "profile_id": agent_profile_id,
                "agent_id": agent_id,
                "leases": requested_leases,
                "skill_invocation": skill_invocation,
            }
            _record_image_attachment_router_event(
                conversation_id,
                turn_id=turn_control.turn_id,
                route="image2",
                intent=image_route["intent"],
                outcome="scheduled",
                agent_profile_id=agent_profile_id,
                agent_id=agent_id,
                attachments=attachments,
                fields={"supportsImageInput": image_route.get("supports_image_input")},
            )
            _record_session_turn_scheduled_event(context)
            try:
                _schedule_image2_attachment_turn(context)
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
            detail = get_session_detail(conversation_id) or {}
            if include_started_turn_id:
                detail["startedTurnId"] = turn_control.turn_id
            return detail

    if normalized_message_source == "agent_inbox":
        effective_user_message, user_message_source = message, normalized_message_source
    elif attachments:
        effective_user_message = message or text_for(
            lang,
            zh="请查看本轮图片附件并回答。",
            en="Please inspect the image attachment(s) from this turn and respond.",
        )
        user_message_source = "raw_with_attachments" if message else "attachments_only"
    else:
        effective_user_message, user_message_source = _resolve_session_user_prompt(
            conversation_id,
            message,
            previous_messages,
            existing_task=active_task,
        )
        if effective_user_message == message and normalized_message_source != "raw":
            user_message_source = normalized_message_source
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
        "history_messages": previous_messages,
        "mental_model_enabled": mental_model_enabled,
        "active_task": active_task,
        "profile_id": agent_profile_id,
        "agent_id": agent_id,
        "skill_invocation": skill_invocation,
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
    detail = get_session_detail(conversation_id) or {}
    if include_started_turn_id:
        detail["startedTurnId"] = turn_control.turn_id
    return detail


def wake_agent_for_inbox_message(message: dict[str, Any]) -> dict[str, Any]:
    """Start the target Agent's direct session so it can answer an inbox message."""

    message_id = str(message.get("messageId") or message.get("eventId") or "").strip()
    target_agent_id = str(message.get("targetAgentId") or "").strip()
    target_agent = get_agent(target_agent_id) if target_agent_id else None
    target_session_id = str(message.get("targetSessionId") or (target_agent or {}).get("directSessionId") or "").strip()
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
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "sourceAgentCode": str(message.get("sourceAgentCode") or "").strip(),
                "sourceSessionId": str(message.get("sourceSessionId") or "").strip(),
                "targetAgentId": target_agent_id,
                "targetSessionId": target_session_id,
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
    """Replace a historical user message, truncate later turns, and start a new turn."""

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

        if _is_session_running(conversation_id):
            raise SessionBusyError(
                text_for(
                    lang,
                    zh="当前会话仍在运行，请等这一轮结束后再重新编辑发送。",
                    en="This session is still running. Wait for the current turn to finish before editing and resending.",
                )
            )

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
            raise SessionBusyError(_localize_lease_conflict(lease_decision.reason, lang=lang))

        _ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = get_agent(agent_id) if agent_id else None
        agent_profile_id = _normalize_session_agent_profile_id(
            (agent or {}).get("profileId")
            or conversation.get("agent_profile_id")
            or conversation.get("agentProfileId")
            or DEFAULT_SESSION_AGENT_PROFILE_ID
        )
        original_entry = dict(previous_messages[target_index])
        user_metadata = {}
        if skill_invocation:
            user_metadata["slashSkillCommand"] = {
                "command": skill_invocation.get("command", ""),
                "skillName": skill_invocation.get("skillName", ""),
                "skillHash": skill_invocation.get("skillHash", ""),
            }
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
        turn_control = _create_session_turn_control(conversation_id)
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
        "profile_id": agent_profile_id,
        "agent_id": agent_id,
        "skill_invocation": skill_invocation,
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


def _load_conversations() -> tuple[str, list[dict[str, Any]]]:
    payload = load_chat_state(PROJECT_ROOT)
    payload = _repair_stale_running_conversations(payload)
    active_id = str(payload.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    conversations: list[dict[str, Any]] = []
    changed = False
    agent_by_id = _agent_lookup_for_conversations()
    for raw in list(payload.get("conversations") or []):
        if isinstance(raw, dict):
            changed = _ensure_conversation_workspace_metadata(raw) or changed
            changed = _ensure_conversation_agent_metadata(raw, agent_by_id=agent_by_id) or changed
        conversation = _normalize_conversation(raw, agent_by_id=agent_by_id)
        if conversation is not None:
            conversations.append(conversation)
    if changed:
        payload["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    return active_id or DEFAULT_CHAT_CONVERSATION_ID, conversations


def _append_agent_directory_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_session_id = {
        str(item.get("id") or "").strip(): item
        for item in conversations
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    result = list(conversations)
    try:
        agents = agent_directory_service.list_agents(include_archived=False)
    except Exception:
        return result
    for agent in agents:
        if not isinstance(agent, dict):
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


def _agent_directory_conversation_stub(agent: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
    return {
        "id": session_id,
        "title": display_name,
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentProfileId": _normalize_session_agent_profile_id(agent.get("profileId") or DEFAULT_SESSION_AGENT_PROFILE_ID),
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
    now = ""
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        conversation_id = str(conversation.get("conversation_id") or "").strip()
        persisted_status = str(conversation.get("last_turn_status") or "").strip().lower()
        if persisted_status not in {"queued", "running", "stopping"}:
            continue
        if conversation_id and _is_session_running(conversation_id):
            continue
        if not now:
            now = _now_timestamp()
        messages = normalize_chat_messages(conversation.get("messages") or [])
        stop_message = _make_chat_message(
            "assistant",
            text_for(
                get_web_language(),
                zh="上一轮运行已被中断，当前会话已恢复为可继续状态。",
                en="The previous turn was interrupted. This session is ready to continue.",
            ),
        )
        conversation["messages"] = messages + [stop_message]
        conversation["last_turn_status"] = "ready"
        conversation["updated_at"] = stop_message["timestamp"]
        _release_stale_chat_turn_work_run(
            session_id=conversation_id,
            finished_at=str(stop_message["timestamp"] or now),
            summary=str(stop_message.get("content") or ""),
        )
        changed = True
    if changed:
        payload["updated_at"] = now or _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    return payload


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
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    conversation_id = str(raw.get("conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return None
    workspace_path = _session_workspace_relative_path(conversation_id)
    _ensure_session_workspace(conversation_id)
    title = str(raw.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE).strip() or DEFAULT_CHAT_CONVERSATION_TITLE
    agent_profile_id = _normalize_session_agent_profile_id(
        raw.get("agent_profile_id") or raw.get("agentProfileId") or DEFAULT_SESSION_AGENT_PROFILE_ID
    )
    agent_id = str(raw.get("agent_id") or raw.get("agentId") or "").strip()
    agent = _agent_from_lookup(agent_by_id, agent_id) if agent_id else None
    if agent:
        agent_profile_id = _normalize_session_agent_profile_id(agent.get("profileId") or agent_profile_id)
    messages = _normalize_messages(conversation_id, raw.get("messages") or [])
    last_turn_status = str(raw.get("last_turn_status") or "").strip().lower()
    last_turn_error = _normalize_session_turn_error(raw.get("last_turn_error") or raw.get("lastTurnError"))
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
        "agentProfileId": agent_profile_id,
        "workspacePath": workspace_path,
        "messages": messages,
        "lastTurnStatus": last_turn_status,
        "lastTurnError": last_turn_error,
        "updatedAt": updated_at,
        "activeTask": dict(active_task or {}) if isinstance(active_task, dict) else None,
        "_agent": dict(agent) if isinstance(agent, dict) else None,
    }


def _normalize_messages(conversation_id: str, items: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, raw in enumerate(list(items or []), start=1):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _sanitize_message_content(role, raw.get("content") or "")
        thought = _normalize_message_thought(raw, role=role)
        mental_snapshot = _normalize_mental_snapshot(raw.get("mental_snapshot") or raw.get("mentalSnapshot"))
        tool_calls = _normalize_message_tool_calls(raw.get("tool_calls") or raw.get("toolCalls") or raw.get("tools") or [])
        attachments = _normalize_message_attachments(raw.get("attachments") or raw.get("imageAttachments") or [])
        if not content and not thought and mental_snapshot is None and not tool_calls and not attachments:
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
        if attachments:
            entry["attachments"] = attachments
        metadata = raw.get("metadata")
        if isinstance(metadata, dict) and metadata:
            entry["metadata"] = dict(metadata)
        messages.append(entry)
    return messages


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


def _should_omit_message_from_agent_history(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    content = str(message.get("content") or "").strip()
    attachments = _normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
    if role != "user":
        return role == "assistant" and (
            not content
            or _is_protocol_only_assistant_message(content)
            or _looks_like_provider_error_text(content)
            or _looks_like_runtime_failure_notice(content)
        )
    return not attachments and not _is_meaningful_task_goal(content)


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
    return _is_meaningful_task_goal(message) and not _is_contextual_confirmation_message(message)


def _latest_effective_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        content = trim_lines(item.get("content") or "", max_lines=4)
        if _is_effective_user_message(content):
            return content
    return ""


def _latest_effective_user_messages(messages: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
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


def _resolve_session_user_prompt(
    session_id: str,
    raw_message: Any,
    history_messages: list[dict[str, Any]],
    *,
    existing_task: dict[str, Any] | None = None,
) -> tuple[str, str]:
    prompt = trim_lines(raw_message or "", max_lines=4)
    if _is_continue_request(prompt):
        return prompt, "continue"
    if _is_effective_user_message(prompt):
        return prompt, "raw_meaningful"

    existing_goal = ""
    if isinstance(existing_task, dict):
        existing_goal = trim_lines(existing_task.get("goal") or existing_task.get("title") or "", max_lines=2)
    if existing_goal and _is_effective_user_message(existing_goal):
        if _is_contextual_confirmation_message(prompt):
            return _build_contextual_confirmation_prompt(prompt, existing_goal, existing_task=existing_task), "active_task_confirmation"
        return existing_goal, "active_task_fallback"

    history_goal = _latest_effective_user_message(history_messages)
    if history_goal:
        return history_goal, "history_fallback"

    return prompt, "raw_non_meaningful"


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
        "模型服务上游暂时失败，本轮没有完成",
        "the previous turn was interrupted. this session is ready to continue",
        "the model provider failed upstream, so this turn did not complete",
    )
    return any(notice in value for notice in notices)


def _find_user_message_index_by_api_id(
    conversation_id: str,
    messages: list[dict[str, Any]],
    message_id: str,
) -> int:
    normalized_target = str(message_id or "").strip()
    if not normalized_target:
        return -1
    for index, item in enumerate(list(messages or []), start=1):
        role = str(item.get("role") or "").strip().lower()
        api_id = str(item.get("id") or f"{conversation_id}-message-{index}").strip()
        if api_id == normalized_target and role == "user":
            return index - 1
    return -1


def _latest_user_message_index(messages: list[dict[str, Any]]) -> int:
    for index in range(len(messages or []) - 1, -1, -1):
        if str((messages[index] or {}).get("role") or "").strip().lower() == "user":
            return index
    return -1


def _sanitize_message_content(role: str, content: Any) -> str:
    text = str(content or "").strip()
    if str(role or "").strip().lower() != "assistant":
        return text
    return sanitize_assistant_visible_text(text)


def _normalize_message_attachments(value: Any) -> list[dict[str, Any]]:
    return normalize_chat_attachments(value)


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


def _build_session_summary(conversation: dict[str, Any]) -> dict[str, Any]:
    status = _conversation_phase(conversation["id"], conversation)
    summary = _latest_message_summary(conversation.get("messages") or [])
    updated_at = str(conversation.get("updatedAt") or "").strip()
    agent_id = str(conversation.get("agentId") or "").strip()
    cached_agent = conversation.get("_agent")
    agent = cached_agent if isinstance(cached_agent, dict) else (get_agent(agent_id) if agent_id else None)
    agent_profile_id = _normalize_session_agent_profile_id(
        (agent or {}).get("profileId") or conversation.get("agentProfileId") or DEFAULT_SESSION_AGENT_PROFILE_ID
    )
    agent_workspace_path = str((agent or {}).get("workspacePath") or "").strip()
    agent_code = str((agent or {}).get("agentCode") or "").strip()
    agent_primary_mode = str((agent or {}).get("primaryMode") or "").strip()
    agent_role_key = str((agent or {}).get("roleKey") or "").strip()
    agent_prompt_template_id = str((agent or {}).get("promptTemplateId") or "").strip()
    agent_status = _session_agent_status_payload(agent_id, agent)
    agent_display_name = str((agent or {}).get("displayName") or "").strip()
    if agent_status["agentMissing"] and not agent_display_name:
        agent_display_name = text_for(get_web_language(), zh="缺少有效 Agent", en="Missing Agent")
    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "agentId": agent_id,
        "agentCode": agent_code,
        "agentDisplayName": agent_display_name or str(conversation["title"]).strip(),
        "agentProfileId": agent_profile_id,
        "agentTemplateId": agent_profile_id,
        "agentTemplateLabel": _session_agent_profile_label(agent_profile_id, get_web_language()),
        "agentPrimaryMode": agent_primary_mode,
        "agentRoleKey": agent_role_key,
        "agentPromptTemplateId": agent_prompt_template_id,
        "workspacePath": str(conversation.get("workspacePath") or _session_workspace_relative_path(conversation["id"])),
        "agentWorkspacePath": agent_workspace_path,
        **agent_status,
        "status": status,
        "taskSummary": summary,
        "lastActive": updated_at,
        "updatedAt": updated_at,
        "currentPhase": status,
    }


def _build_session_detail(conversation: dict[str, Any]) -> dict[str, Any]:
    summary = _build_session_summary(conversation)
    turn_control = _get_session_turn_control(conversation["id"])
    turn_snapshot = turn_control.snapshot() if turn_control is not None else {
        "stopRequested": False,
        "stopRequestedAt": "",
        "stopReason": "",
    }
    active_task = _normalize_session_active_task(
        conversation.get("active_task") or conversation.get("activeTask")
    )
    changed_files = list(active_task.get("changed_files") or []) if active_task else []
    read_files = list(active_task.get("read_files") or []) if active_task else []
    preview_tabs = list(active_task.get("preview_tabs") or []) if active_task else []
    default_file_context = str(active_task.get("default_file_context") or "").strip() if active_task else ""
    active_preview_path = (
        str(active_task.get("active_preview_path") or "").strip() if active_task else ""
    ) or "agent"
    detail_messages = _messages_with_live_output(conversation["id"], conversation.get("messages") or [])
    context_usage = _build_session_context_usage(conversation["id"], detail_messages)
    cache_usage = _build_session_cache_usage()
    agent_available = _session_agent_is_available(summary)
    available_agent_id = summary.get("agentId") or "" if agent_available else ""
    available_agent = get_agent(available_agent_id) if available_agent_id else None
    detail = {
        **summary,
        "activeTask": _active_task_to_api(active_task),
        "defaultFileContext": default_file_context,
        "previewTabs": preview_tabs,
        "activePreviewPath": active_preview_path,
        "changedFiles": changed_files,
        "readFiles": read_files,
        "messages": detail_messages,
        "contextUsage": context_usage,
        "cacheUsage": cache_usage,
        "lastTurnError": _session_turn_error_to_api(conversation.get("lastTurnError")),
        "nextStateSignals": _recent_chat_next_state_signal_summaries(conversation["id"], limit=5),
        "groupContextEvents": list_group_context_events_for_agent(available_agent_id, limit=8)
        if available_agent_id
        else [],
        "agentInboxMessages": list_agent_inbox_messages_for_agent(available_agent_id, limit=8, status="pending")
        if available_agent_id
        else [],
        "toolPolicy": (available_agent or {}).get("toolPolicy") if available_agent_id else None,
        "memoryPolicy": (available_agent or {}).get("memoryPolicy") if available_agent_id else None,
        "stopRequested": bool(turn_snapshot["stopRequested"]),
        "stopRequestedAt": str(turn_snapshot["stopRequestedAt"] or "").strip(),
        "stopReason": str(turn_snapshot["stopReason"] or "").strip(),
    }
    return detail


def _build_session_cache_usage() -> dict[str, Any]:
    runtime_state_path = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
    try:
        payload = json.loads(runtime_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    turn_input_tokens = _coerce_nonnegative_int(payload.get("turn_input_tokens") or 0)
    turn_cached_input_tokens = min(
        _coerce_nonnegative_int(payload.get("turn_cached_input_tokens") or 0),
        turn_input_tokens,
    ) if turn_input_tokens else 0
    last_input_tokens = _coerce_nonnegative_int(payload.get("last_input_tokens") or 0)
    last_cached_input_tokens = _coerce_nonnegative_int(payload.get("last_cached_input_tokens") or 0)
    if not last_input_tokens and last_cached_input_tokens:
        last_input_tokens = turn_input_tokens
    if last_input_tokens:
        last_cached_input_tokens = min(last_cached_input_tokens, last_input_tokens)
    else:
        last_cached_input_tokens = 0
    total_input_tokens = _coerce_nonnegative_int(payload.get("total_input_tokens") or 0)
    total_cached_input_tokens = min(
        _coerce_nonnegative_int(payload.get("total_cached_input_tokens") or 0),
        total_input_tokens,
    ) if total_input_tokens else 0
    return {
        "lastInputTokens": last_input_tokens,
        "lastCachedInputTokens": last_cached_input_tokens,
        "turnInputTokens": turn_input_tokens,
        "turnCachedInputTokens": turn_cached_input_tokens,
        "turnCacheHitRate": (turn_cached_input_tokens / turn_input_tokens) if turn_input_tokens > 0 else 0.0,
        "totalInputTokens": total_input_tokens,
        "totalCachedInputTokens": total_cached_input_tokens,
        "totalCacheHitRate": (total_cached_input_tokens / total_input_tokens) if total_input_tokens > 0 else 0.0,
        "updatedAt": str(payload.get("updated_at") or "").strip(),
        "source": "ui_runtime_state",
    }


def _build_session_context_usage(session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
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
    estimated_tokens = _estimate_session_context_tokens(character_count, tool_call_count)
    limit = _session_context_limit()
    used = min(estimated_tokens, limit) if limit > 0 else estimated_tokens
    payload = {
        "used": used,
        "limit": limit,
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


def _session_context_limit() -> int:
    try:
        cfg = get_config()
        runtime_limit = _runtime_context_window_limit()
        profile = cfg.llm.get_profile(role="primary")
        provider = cfg.llm.get_provider(profile.provider_id)
        resolved_limit = _resolved_model_context_window(cfg, profile.profile_id)
        provider_limit = int(getattr(provider, "context_window", 0) or 0)
        compression_limit = int(getattr(cfg.context_compression, "max_token_limit", 0) or 0)
        return _first_positive_int(runtime_limit, resolved_limit, provider_limit, compression_limit, 128000)
    except Exception:
        return 128000


def _runtime_context_window_limit() -> int:
    runtime_state_path = PROJECT_ROOT / "workspace" / "ui_runtime_state.json"
    try:
        payload = json.loads(runtime_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    compression = payload.get("context_compression")
    compression = compression if isinstance(compression, dict) else {}
    return _first_positive_int(
        compression.get("contextWindowLimit"),
        payload.get("context_token_limit"),
    )


def _resolved_model_context_window(cfg: Any, profile_id: str) -> int:
    try:
        from core.llm.discovery import discover_model

        spec = discover_model(cfg, profile_id)
        return int(getattr(spec, "context_window", 0) or 0)
    except Exception:
        return 0


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


def _latest_assistant_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_summary(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        return _compact_preview_text(item.get("content") or "")
    return ""


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        return trim_lines(item.get("content") or "", max_lines=4)
    return ""


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


def _new_conversation_id(existing_ids: set[str] | None = None) -> str:
    existing = set(existing_ids or set())
    base = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


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


def _normalize_session_agent_profile_id(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized or DEFAULT_SESSION_AGENT_PROFILE_ID


def _session_agent_profile_label(profile_id: str, lang: str) -> str:
    labels = {
        "primary": text_for(lang, zh="主 Agent", en="Primary agent"),
        "subagent_worker": text_for(lang, zh="执行 Agent", en="Worker agent"),
        "subagent_explorer": text_for(lang, zh="探索 Agent", en="Explorer agent"),
        "mental_model": text_for(lang, zh="心智模型 Agent", en="Mental model agent"),
        "supervised_baseline": text_for(lang, zh="监督基线 Agent", en="Supervised baseline agent"),
        "supervised_candidate": text_for(lang, zh="监督候选 Agent", en="Supervised candidate agent"),
        "research_broad": text_for(lang, zh="广搜 Agent", en="Broad research agent"),
        "research_deep": text_for(lang, zh="深搜 Agent", en="Deep research agent"),
        "research_review": text_for(lang, zh="审查 Agent", en="Review agent"),
        "research_themes": text_for(lang, zh="主题 Agent", en="Theme agent"),
        "research_card": text_for(lang, zh="主题卡 Agent", en="Card agent"),
        "compression": text_for(lang, zh="压缩 Agent", en="Compression agent"),
    }
    normalized = _normalize_session_agent_profile_id(profile_id)
    return labels.get(normalized, normalized.replace("_", " ").strip().title() or normalized)


def _validate_session_agent_profile_id(profile_id: str, *, lang: str) -> None:
    normalized = _normalize_session_agent_profile_id(profile_id)
    if normalized not in get_config().llm.profiles:
        raise SessionValidationError(
            text_for(
                lang,
                zh=f"未找到 Agent 模板：{normalized}",
                en=f"Agent template not found: {normalized}",
            )
        )


def _session_agent_config_for_profile(profile_id: str) -> Any:
    normalized = _normalize_session_agent_profile_id(profile_id)
    config = copy.deepcopy(get_config())
    if normalized == DEFAULT_SESSION_AGENT_PROFILE_ID:
        return config
    if normalized not in config.llm.profiles:
        return config
    selected = copy.deepcopy(config.llm.profiles[normalized])
    selected.profile_id = DEFAULT_SESSION_AGENT_PROFILE_ID
    config.llm.profiles[DEFAULT_SESSION_AGENT_PROFILE_ID] = selected
    return config


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


def _classify_image_attachment_intent(message: str) -> str:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return "clarify"
    if any(pattern in normalized for pattern in _IMAGE_ATTACHMENT_IMAGE2_PATTERNS):
        return "image2_edit"
    if any(pattern in normalized for pattern in _IMAGE_ATTACHMENT_VISION_PATTERNS):
        return "vision_analysis"
    return "clarify"


def _resolve_image_attachment_turn_route(message: str, *, agent_profile_id: str) -> dict[str, Any]:
    intent = _classify_image_attachment_intent(message)
    supports_image_input = _session_profile_supports_image_input(agent_profile_id)
    if intent == "image2_edit":
        route = "image2"
    elif intent == "vision_analysis" and supports_image_input is True:
        route = "vision"
    elif intent == "vision_analysis":
        route = "block_vision"
    else:
        route = "clarify"
    return {
        "intent": intent,
        "route": route,
        "supports_image_input": supports_image_input,
    }


def _session_profile_supports_image_input(profile_id: str) -> bool | None:
    normalized_profile_id = _normalize_session_agent_profile_id(profile_id or DEFAULT_SESSION_AGENT_PROFILE_ID)
    try:
        config = get_config()
        profile = config.llm.get_profile(profile_id=normalized_profile_id)
    except Exception:
        return None

    explicit = getattr(profile, "supports_image_input", None)
    if explicit is not None:
        return bool(explicit)

    lowered_model = str(getattr(profile, "model", "") or "").strip().lower()
    lowered_contract = str(getattr(profile, "contract", "") or "").strip().lower()
    lowered_transport = str(getattr(profile, "transport", "") or "").strip().lower()
    haystack = " ".join((lowered_model, lowered_contract, lowered_transport))
    if any(hint in haystack for hint in _VISION_MODEL_NAME_HINTS):
        return True
    return False


def _image_attachment_clarification_message(lang: str) -> str:
    return text_for(
        lang,
        zh="我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
        en="I received your image. Do you want me to analyze it, or generate/edit an image based on it? Please add your goal.",
    )


def _image_input_unsupported_message(lang: str, *, profile_id: str) -> str:
    return text_for(
        lang,
        zh=f"当前 Agent 使用的模型档案 `{profile_id}` 未确认支持图像输入，所以我没有把图片发送给模型。请切换到支持图像输入的模型，或说明要基于这张图生成/调整图片，我会交给 image2 工具处理。",
        en=f"The current Agent profile `{profile_id}` is not confirmed to support image input, so I did not send the image to the model. Switch to a vision-capable model, or ask to generate/edit an image based on it so image2 can handle it.",
    )


def _image2_prompt_from_attachments(lang: str) -> str:
    return text_for(
        lang,
        zh="请基于本轮图片附件生成或调整图片。",
        en="Generate or edit an image based on this turn's image attachment.",
    )


def _finish_image_attachment_routed_turn(
    session_id: str,
    turn_id: str,
    result: dict[str, Any],
    *,
    route: str,
    intent: str,
    agent_profile_id: str,
    agent_id: str,
    attachments: list[dict[str, Any]],
    leases: list[str] | None,
    raw_user_message: str,
    outcome: str = "completed",
    level: str = "info",
) -> None:
    _record_image_attachment_router_event(
        session_id,
        turn_id=turn_id,
        route=route,
        intent=intent,
        outcome=outcome,
        level=level,
        agent_profile_id=agent_profile_id,
        agent_id=agent_id,
        attachments=attachments,
        fields={
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
    agent_profile_id: str,
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
                "agentProfileId": str(agent_profile_id or "").strip(),
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
                "agent_profile_id": str(agent_profile_id or "").strip(),
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
        in {"completed", "failed", "stopped", "cancelled", "paused_limit", "needs_continue", "stopped_by_user"}
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

    normalized_agent_id = str(agent_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    if not normalized_agent_id or not normalized_run_id:
        yield
        return

    agent_key = f"agent:{normalized_agent_id}"
    acquired = False
    ready_event = threading.Event()
    timeout_seconds = float(wait_timeout_seconds or 0.0)
    deadline = time.monotonic() + max(0.1, timeout_seconds) if timeout_seconds > 0 else None
    context = {
        "session_id": str(session_id or "").strip(),
        "turn_id": normalized_run_id,
        "agent_id": normalized_agent_id,
        "_scheduler_agent_key": agent_key,
        "_scheduler_external": True,
        "_scheduler_ready_event": ready_event,
        "_scheduler_cancelled": False,
    }
    _record_session_scheduler_event(
        context,
        "external_waiting",
        outcome="waiting",
        fields={"owner": str(owner or "external").strip() or "external"},
    )
    with _SESSION_AGENT_SCHEDULER_CONDITION:
        active_turn_id = str(_SESSION_AGENT_ACTIVE_TURN_IDS.get(agent_key) or "").strip()
        queued = _SESSION_AGENT_QUEUES.get(agent_key)
        if not active_turn_id and not queued:
            _SESSION_AGENT_ACTIVE_TURN_IDS[agent_key] = normalized_run_id
            acquired = True
        else:
            queue_bucket = _SESSION_AGENT_QUEUES.setdefault(agent_key, deque())
            queue_bucket.append(context)
            _record_session_scheduler_event(
                context,
                "external_queued",
                outcome="queued",
                fields={
                    "owner": str(owner or "external").strip() or "external",
                    "queuePosition": len(queue_bucket),
                },
            )
    while not acquired:
        if bool(context.get("_scheduler_cancelled")):
            raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
        if ready_event.is_set():
            if bool(context.get("_scheduler_cancelled")):
                raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
            acquired = True
            break
        if deadline is None:
            ready_event.wait(timeout=0.25)
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _cancel_queued_scheduler_context(agent_key, normalized_run_id)
                raise TimeoutError(f"Timed out waiting for agent execution slot: {normalized_agent_id}")
            ready_event.wait(timeout=min(0.25, remaining))
        if ready_event.is_set():
            if bool(context.get("_scheduler_cancelled")):
                raise RuntimeError(f"Agent execution slot reservation was cancelled: {normalized_agent_id}")
            acquired = True
    _record_session_scheduler_event(
        context,
        "external_started",
        outcome="running",
        fields={"owner": str(owner or "external").strip() or "external"},
    )
    try:
        yield
    finally:
        if acquired:
            _record_session_scheduler_event(
                context,
                "external_finished",
                outcome="finished",
                fields={"owner": str(owner or "external").strip() or "external"},
            )
            _release_scheduled_session_turn(context)


def _scheduler_context_is_external(context: dict[str, Any]) -> bool:
    return bool(context.get("_scheduler_external"))


def _cancel_queued_scheduler_context(agent_key: str, turn_id: str) -> bool:
    normalized_agent_key = str(agent_key or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_agent_key or not normalized_turn_id:
        return False
    removed = False
    with _SESSION_AGENT_SCHEDULER_CONDITION:
        queue_bucket = _SESSION_AGENT_QUEUES.get(normalized_agent_key)
        if not queue_bucket:
            return False
        kept: deque[dict[str, Any]] = deque()
        while queue_bucket:
            queued_context = queue_bucket.popleft()
            if str(queued_context.get("turn_id") or "").strip() == normalized_turn_id:
                removed = True
                queued_context["_scheduler_cancelled"] = True
                ready_event = queued_context.get("_scheduler_ready_event")
                if isinstance(ready_event, threading.Event):
                    ready_event.set()
                continue
            kept.append(queued_context)
        if kept:
            _SESSION_AGENT_QUEUES[normalized_agent_key] = kept
        else:
            _SESSION_AGENT_QUEUES.pop(normalized_agent_key, None)
        if removed:
            _SESSION_AGENT_SCHEDULER_CONDITION.notify_all()
    return removed


def cancel_agent_execution_reservation(run_id: str) -> bool:
    """Cancel queued external work that is waiting for an agent execution slot."""

    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return False
    removed = False
    with _SESSION_AGENT_SCHEDULER_CONDITION:
        for agent_key in list(_SESSION_AGENT_QUEUES):
            queue_bucket = _SESSION_AGENT_QUEUES.get(agent_key)
            if not queue_bucket:
                _SESSION_AGENT_QUEUES.pop(agent_key, None)
                continue
            kept: deque[dict[str, Any]] = deque()
            while queue_bucket:
                queued_context = queue_bucket.popleft()
                queued_turn_id = str(queued_context.get("turn_id") or "").strip()
                if _scheduler_context_is_external(queued_context) and queued_turn_id == normalized_run_id:
                    removed = True
                    queued_context["_scheduler_cancelled"] = True
                    ready_event = queued_context.get("_scheduler_ready_event")
                    if isinstance(ready_event, threading.Event):
                        ready_event.set()
                    _record_session_scheduler_event(
                        queued_context,
                        "external_cancelled",
                        outcome="cancelled",
                        fields={"reason": "external_run_cancelled"},
                    )
                    continue
                kept.append(queued_context)
            if kept:
                _SESSION_AGENT_QUEUES[agent_key] = kept
            else:
                _SESSION_AGENT_QUEUES.pop(agent_key, None)
        if removed:
            _SESSION_AGENT_SCHEDULER_CONDITION.notify_all()
    return removed


def _schedule_session_turn(context: dict[str, Any]) -> None:
    job_context = dict(context)
    agent_key = _session_scheduler_agent_key(job_context)
    job_context["_scheduler_agent_key"] = agent_key
    context["_scheduler_agent_key"] = agent_key
    turn_id = str(job_context.get("turn_id") or "").strip()
    queued_position = 0
    should_start = False
    with _SESSION_AGENT_SCHEDULER_LOCK:
        if _SESSION_AGENT_ACTIVE_TURN_IDS.get(agent_key):
            queue_bucket = _SESSION_AGENT_QUEUES.setdefault(agent_key, deque())
            queue_bucket.append(job_context)
            queued_position = len(queue_bucket)
        else:
            _SESSION_AGENT_ACTIVE_TURN_IDS[agent_key] = turn_id
            should_start = True

    if not should_start:
        _mark_session_turn_queued(job_context, queue_position=queued_position)
        return

    _record_session_scheduler_event(job_context, "started", outcome="running")
    try:
        _submit_scheduled_session_turn(job_context)
    except Exception:
        _release_scheduled_session_turn(job_context)
        raise


def _submit_scheduled_session_turn(context: dict[str, Any]) -> None:
    _SESSION_EXECUTOR.submit(_execute_scheduled_session_turn, context)


def _schedule_image2_attachment_turn(context: dict[str, Any]) -> None:
    _SESSION_EXECUTOR.submit(_execute_image2_attachment_turn, dict(context))


def _execute_image2_attachment_turn(context: dict[str, Any]) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    agent_id = str(context.get("agent_id") or "").strip()
    agent_profile_id = _normalize_session_agent_profile_id(context.get("profile_id") or DEFAULT_SESSION_AGENT_PROFILE_ID)
    attachments = _normalize_message_attachments(context.get("attachments") or [])
    try:
        if turn_id and not _is_session_turn_current(session_id, turn_id):
            _record_session_turn_lifecycle_event(
                session_id,
                "image2_router_skipped_stale",
                turn_id=turn_id,
                outcome="skipped",
                fields={"reason": "turn_id_not_current"},
            )
            return
        _record_image_attachment_router_event(
            session_id,
            turn_id=turn_id,
            route="image2",
            intent="image2_edit",
            outcome="running",
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            attachments=attachments,
        )
        prompt = str(context.get("user_message") or "").strip() or _image2_prompt_from_attachments(get_web_language())
        artifact_ids = [
            str(item.get("artifactId") or "").strip()
            for item in attachments
            if str(item.get("artifactId") or "").strip()
        ]
        if not artifact_ids:
            raise SessionValidationError("No image attachment artifact is available for image2.")

        from tools.image2_tools import image2_generate_tool

        with active_agent_runtime(agent_id, session_id=session_id, turn_id=turn_id):
            tool_result_text = image2_generate_tool(
                prompt=prompt,
                input_artifact_id=artifact_ids[0],
            )
        try:
            tool_result = json.loads(tool_result_text)
        except (TypeError, ValueError):
            tool_result = {"ok": False, "status": "failed", "message": str(tool_result_text or "")}
        ok = bool(tool_result.get("ok")) if isinstance(tool_result, dict) else False
        summary = (
            text_for(get_web_language(), zh="已基于图片生成新图片。", en="Generated a new image based on the attachment.")
            if ok
            else str((tool_result or {}).get("message") or "image2 failed")
        )
        _record_image_attachment_router_event(
            session_id,
            turn_id=turn_id,
            route="image2",
            intent="image2_edit",
            outcome="succeeded" if ok else "failed",
            level="info" if ok else "warning",
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            attachments=attachments,
            fields={
                "toolStatus": str((tool_result or {}).get("status") or "").strip(),
                "artifactId": str((tool_result or {}).get("artifactId") or "").strip(),
                "inputArtifactId": artifact_ids[0],
            },
        )
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status="completed" if ok else "failed",
            agent_id=agent_id,
            leases=list(context.get("leases") or ["readonly_chat"]),
            user_message=str(context.get("raw_user_message") or prompt).strip(),
            summary=summary,
            error_type="" if ok else str((tool_result or {}).get("errorType") or "image2_failed"),
            error="" if ok else str((tool_result or {}).get("message") or ""),
            finished_at=_now_timestamp(),
        )
        if ok:
            with _CHAT_STATE_LOCK:
                payload = load_chat_state(PROJECT_ROOT)
                conversation = _find_conversation_entry(payload, session_id)
                if conversation is not None:
                    conversation["last_turn_status"] = "ready"
                    conversation.pop("last_turn_error", None)
                    conversation.pop("lastTurnError", None)
                    conversation["updated_at"] = _now_timestamp()
                    payload["updated_at"] = conversation["updated_at"]
                    save_chat_state(PROJECT_ROOT, payload)
        else:
            _persist_session_turn_result(
                session_id,
                {
                    "status": "failed_runtime",
                    "summary": f"图片生成失败：{summary}",
                    "raw_output": f"图片生成失败：{summary}",
                    "error": summary,
                    "outcome": "failed",
                },
                turn_id=turn_id,
            )
    except Exception as exc:
        _record_session_turn_lifecycle_event(
            session_id,
            "image2_router_exception",
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
        _set_session_running(session_id, False, turn_id=turn_id)
        _clear_session_turn_control(session_id, turn_id=turn_id)
        _publish_session_detail_snapshot(session_id)


def _execute_scheduled_session_turn(context: dict[str, Any]) -> None:
    try:
        _run_session_turn(context)
    finally:
        _release_scheduled_session_turn(context)


def _release_scheduled_session_turn(context: dict[str, Any]) -> None:
    agent_key = str(context.get("_scheduler_agent_key") or _session_scheduler_agent_key(context)).strip()
    turn_id = str(context.get("turn_id") or "").strip()
    next_context: dict[str, Any] | None = None
    dropped_contexts: list[dict[str, Any]] = []
    with _SESSION_AGENT_SCHEDULER_LOCK:
        if _SESSION_AGENT_ACTIVE_TURN_IDS.get(agent_key) == turn_id:
            _SESSION_AGENT_ACTIVE_TURN_IDS.pop(agent_key, None)
        queue_bucket = _SESSION_AGENT_QUEUES.get(agent_key)
        while queue_bucket:
            candidate = queue_bucket.popleft()
            candidate_session_id = str(candidate.get("session_id") or "").strip()
            candidate_turn_id = str(candidate.get("turn_id") or "").strip()
            if bool(candidate.get("_scheduler_cancelled")):
                dropped_contexts.append(candidate)
                continue
            if _scheduler_context_is_external(candidate):
                ready_event = candidate.get("_scheduler_ready_event")
                next_context = candidate
                _SESSION_AGENT_ACTIVE_TURN_IDS[agent_key] = candidate_turn_id
                if isinstance(ready_event, threading.Event):
                    ready_event.set()
                break
            if _is_session_running(candidate_session_id) and _is_session_turn_current(candidate_session_id, candidate_turn_id):
                next_context = candidate
                _SESSION_AGENT_ACTIVE_TURN_IDS[agent_key] = candidate_turn_id
                break
            dropped_contexts.append(candidate)
        if queue_bucket is not None and not queue_bucket:
            _SESSION_AGENT_QUEUES.pop(agent_key, None)
        _SESSION_AGENT_SCHEDULER_CONDITION.notify_all()

    for dropped in dropped_contexts:
        _record_session_scheduler_event(dropped, "dropped_stale", outcome="skipped")

    if next_context is None:
        return
    if _scheduler_context_is_external(next_context):
        _record_session_scheduler_event(next_context, "external_dequeued", outcome="running")
        return

    _mark_session_turn_dequeued(next_context)
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
    removed = False
    with _SESSION_AGENT_SCHEDULER_LOCK:
        for agent_key in list(_SESSION_AGENT_QUEUES):
            queue_bucket = _SESSION_AGENT_QUEUES.get(agent_key)
            if not queue_bucket:
                _SESSION_AGENT_QUEUES.pop(agent_key, None)
                continue
            kept: deque[dict[str, Any]] = deque()
            while queue_bucket:
                queued_context = queue_bucket.popleft()
                queued_session_id = str(queued_context.get("session_id") or "").strip()
                queued_turn_id = str(queued_context.get("turn_id") or "").strip()
                if queued_session_id == normalized_session_id and (
                    not normalized_turn_id or queued_turn_id == normalized_turn_id
                ):
                    removed = True
                    continue
                kept.append(queued_context)
            if kept:
                _SESSION_AGENT_QUEUES[agent_key] = kept
            else:
                _SESSION_AGENT_QUEUES.pop(agent_key, None)
        if removed:
            _SESSION_AGENT_SCHEDULER_CONDITION.notify_all()
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
        fields={"queuePosition": max(1, int(queue_position or 1))},
    )
    _publish_session_detail_snapshot(session_id)


def _mark_session_turn_dequeued(context: dict[str, Any]) -> None:
    session_id = str(context.get("session_id") or "").strip()
    turn_id = str(context.get("turn_id") or "").strip()
    if not session_id or not _is_session_turn_current(session_id, turn_id):
        return
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
    _record_session_scheduler_event(context, "dequeued", outcome="running")
    _publish_session_detail_snapshot(session_id)


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
            **(fields or {}),
        },
    )


def _run_session_turn(context: dict[str, Any]) -> None:
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
    session_workspace = _ensure_session_workspace(session_id)
    _sync_agent_directory_project_root()
    agent_id = str(context.get("agent_id") or context.get("agentId") or "").strip()
    agent = get_agent(agent_id) if agent_id else None
    agent_context_packet = (
        build_agent_context(agent_id, session_id=session_id, run_id=turn_id)
        if agent_id
        else None
    )
    agent_workspace = str((agent or {}).get("workspacePath") or "").strip()
    memory_policy = (
        agent_context_packet.memory_policy
        if agent_context_packet is not None
        else (resolve_memory_policy_for_agent(agent_id) if agent_id else {})
    )
    memory_root = str(memory_policy.get("privateMemoryRoot") or "").strip()
    agent_workspace_path = (
        agent_directory_service._ensure_agent_workspace(str((agent or {}).get("workspacePath") or "")).resolve()
        if agent and str((agent or {}).get("workspacePath") or "").strip()
        else session_workspace
    )
    workspace_decision = (
        evaluate_agent_workspace_write(agent_id, agent_workspace_path, purpose="chat_turn_tool_workspace")
        if agent_id
        else None
    )
    tool_workspace = agent_workspace_path if not workspace_decision or workspace_decision.allowed else session_workspace
    _record_session_turn_lifecycle_event(
        session_id,
        "worker_started",
        turn_id=turn_id,
        outcome="running",
        fields={
            "workspacePath": _session_workspace_relative_path(session_id),
            "hasTurnControl": isinstance(turn_control, SessionTurnControl),
            "mentalModelEnabled": mental_model_enabled,
            "agentProfileId": _normalize_session_agent_profile_id(
                context.get("profile_id") or DEFAULT_SESSION_AGENT_PROFILE_ID
            ),
            "agentId": agent_id,
            "agentWorkspacePath": agent_workspace,
            "agentMemoryRoot": memory_root,
            "toolWorkspacePath": str(tool_workspace),
            "toolWorkspaceScope": str(getattr(workspace_decision, "scope", "") or ""),
        },
    )
    effective_agent_profile_id = _normalize_session_agent_profile_id(
        (agent or {}).get("profileId")
        or context.get("profile_id")
        or DEFAULT_SESSION_AGENT_PROFILE_ID
    )
    _record_session_turn_lifecycle_event(
        session_id,
        "agent_runtime_resolved",
        turn_id=turn_id,
        outcome="resolved" if agent else "fallback",
        fields={
            "mode": "chat",
            "agentId": agent_id,
            "agentCode": str((agent or {}).get("agentCode") or "").strip(),
            "profileId": effective_agent_profile_id,
            "promptTemplateId": str((agent or {}).get("promptTemplateId") or "").strip(),
            "roleKey": str((agent or {}).get("roleKey") or "").strip(),
            "source": "AgentInstance" if agent else "profile_id",
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
        with (
            active_agent_runtime(agent_id, session_id=session_id, turn_id=turn_id),
            mental_model_enabled_override(mental_model_enabled),
            _session_tool_workspace_override(tool_workspace, memory_workspace=agent_workspace_path if agent else tool_workspace),
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
                agent_profile_id = effective_agent_profile_id
                agent = _create_chat_agent_for_session(tool_workspace, agent_profile_id=agent_profile_id)
                attachments = _normalize_message_attachments(context.get("attachments") or [])
                _record_session_turn_lifecycle_event(
                    session_id,
                    "agent_created",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "agentType": type(agent).__name__,
                        "workspacePath": _session_workspace_relative_path(session_id),
                        "toolWorkspacePath": str(tool_workspace),
                        "agentProfileId": agent_profile_id,
                        "agentId": agent_id,
                        "promptTemplateId": str((get_agent(agent_id) or {}).get("promptTemplateId") or "").strip() if agent_id else "",
                        "attachmentCount": len(attachments),
                    },
                )
                mental_override_configurer = getattr(agent, "set_mental_model_enabled_override", None)
                if callable(mental_override_configurer):
                    mental_override_configurer(mental_model_enabled)
                restore = getattr(agent, "seed_chat_history", None)
                runtime_context_seed = getattr(agent, "seed_runtime_context", None)
                stop_configurer = getattr(agent, "set_turn_interrupt_checker", None)
                if callable(stop_configurer):
                    stop_configurer(lambda: _get_turn_control_stop_reason(turn_control))
                history_messages = _history_messages_for_agent_seed(context.get("history_messages") or [])
                runtime_context_block = agent_context_packet.context_block if agent_context_packet is not None else ""
                skill_invocation = context.get("skill_invocation")
                skill_runtime_context_block = _skill_runtime_context_from_invocation(skill_invocation)
                if callable(restore) and history_messages:
                    restore(history_messages)
                if callable(runtime_context_seed) and runtime_context_block:
                    runtime_context_seed(runtime_context_block)
                if callable(runtime_context_seed) and skill_runtime_context_block:
                    runtime_context_seed(skill_runtime_context_block)
                    _record_session_skill_command_event(
                        session_id,
                        turn_id=turn_id,
                        invocation=skill_invocation,
                        outcome="routed",
                    )
                _record_session_turn_lifecycle_event(
                    session_id,
                    "history_seeded",
                    turn_id=turn_id,
                    outcome="running",
                    fields={
                        "rawHistoryMessageCount": len(list(context.get("history_messages") or [])),
                        "seededHistoryMessageCount": len(history_messages),
                        "agentRuntimeContextIncluded": bool(runtime_context_block),
                        "skillRuntimeContextIncluded": bool(skill_runtime_context_block),
                        "restoreAvailable": callable(restore),
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
                result = _run_session_continuation_loop(
                    agent,
                    session_id=session_id,
                    turn_control=turn_control,
                    initial_prompt=user_message,
                    history_messages=history_messages,
                    attachments=llm_attachments,
                )
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
    agent_profile_id: str = DEFAULT_SESSION_AGENT_PROFILE_ID,
) -> Any:
    agent_config = _session_agent_config_for_profile(agent_profile_id)
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


def _run_session_continuation_loop(
    agent: Any,
    *,
    session_id: str,
    turn_control: SessionTurnControl | None = None,
    initial_prompt: str,
    history_messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
) -> Any:
    prompt = str(initial_prompt or "").strip()
    has_initial_attachments = bool(list(attachments or []))
    if not has_initial_attachments and not _is_continue_request(prompt) and not _is_effective_user_message(prompt):
        history_goal = _latest_effective_user_message(history_messages)
        if history_goal:
            _record_session_turn_lifecycle_event(
                session_id,
                "user_message_filtered",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="ignored",
                fields={
                    "reason": "non_meaningful_user_message",
                    "messageLength": len(prompt),
                    "questionMarkCount": prompt.count("?"),
                    "fallbackSource": "history",
                },
            )
            prompt = history_goal
    if _is_continue_request(prompt):
        resume_goal, resume_source = _latest_unfinished_task_goal_with_source(session_id)
        if resume_goal:
            prompt = resume_goal
            _set_session_turn_progress_live_output(
                session_id,
                "history_restore",
                turn_id=getattr(turn_control, "turn_id", ""),
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "resume_goal_resolved",
                turn_id=getattr(turn_control, "turn_id", ""),
                outcome="running",
                fields={
                    "resumeGoalLength": len(resume_goal),
                    "historyMessageCount": len(history_messages),
                    "promptSource": resume_source or "resume_goal",
                    "preservesOriginalGoal": True,
                },
            )
            _record_session_turn_trace_event(
                session_id,
                getattr(turn_control, "turn_id", ""),
                "continue",
                {
                    "resumeGoalLength": len(resume_goal),
                    "historyMessageCount": len(history_messages),
                    "promptSource": resume_source or "resume_goal",
                },
                status="running",
                summary="Continue command resolved to the existing user goal.",
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
        result = run_existing_agent_single_turn(agent, initial_prompt=prompt, attachments=turn_attachments)
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

        prompt = _build_followup_prompt(
            original_prompt=initial_prompt,
            effective_prompt=prompt,
            latest_result=result,
            history_messages=history_messages,
            turn_index=turn_index,
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
    turn_id: str = "",
) -> None:
    lang = get_web_language()
    capture_messages: list[dict[str, Any]] | None = None
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
            turn_error = _make_session_turn_error(raw_error, lang=lang, error_type=error_type, turn_id=turn_id)
            timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
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
            )
            if next_active_task is not None:
                conversation["active_task"] = next_active_task
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)
            _clear_session_live_output(session_id)
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
                    "providerFailure": True,
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
        assistant_entry = _make_chat_message(
            "assistant",
            assistant_text,
            _extract_chat_tool_calls(result),
            thought=_extract_chat_thought(result, assistant_text),
            mental_snapshot=_build_turn_mental_snapshot(
                result,
                lang,
                mental_model_enabled=mental_model_enabled,
                session_workspace=session_workspace or _ensure_session_workspace(session_id),
            ),
        )
        if isinstance(result, dict):
            assistant_entry["toolCalls"] = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
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
        )
        if next_active_task is not None:
            conversation["active_task"] = next_active_task
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        final_status = _chat_turn_result_status(result_status, result, stop_requested=stop_requested)
        conversation["last_turn_status"] = (
            "failed"
            if final_status in {"failed_provider", "failed_runtime", "failed"}
            else ("paused_limit" if final_status == "paused_limit" else "ready")
        )
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id)
        if final_status == "completed":
            capture_messages = list(conversation["messages"])
        cycle_active_task = next_active_task
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_id,
            status=final_status,
            summary=assistant_text,
            finished_at=assistant_entry["timestamp"],
            updated_at=assistant_entry["timestamp"],
        )
        tool_calls = _normalize_message_tool_calls(_extract_chat_tool_calls(result))
        _record_session_turn_visible_message(
            session_id,
            turn_id,
            assistant_entry,
            event="assistant_result",
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
                "messageCount": len(conversation.get("messages") or []),
                "assistantTextLength": len(assistant_text),
                "toolCallCount": len(_extract_chat_tool_calls(result)),
                "hasThought": bool(assistant_entry.get("thought")),
                "hasMentalSnapshot": bool(assistant_entry.get("mental_snapshot")),
                "phantomImageSuccess": phantom_image_success,
            },
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
    _record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_result",
        status=final_status,
        active_task=cycle_active_task,
    )
    if capture_messages:
        _capture_session_chat_candidate(session_id, capture_messages)


def _persist_session_turn_failure(session_id: str, context: dict[str, Any], exc: Exception) -> None:
    lang = get_web_language()
    raw_error = str(exc or "").strip()
    error_type = _failure_error_type(raw_error, exc=exc)
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
            turn_error = _make_session_turn_error(raw_error, lang=lang, error_type=error_type, turn_id=str(context.get("turn_id") or ""))
            timestamp = str(turn_error.get("timestamp") or _now_timestamp()).strip()
            conversation["last_turn_status"] = "failed"
            conversation["last_turn_error"] = turn_error
            conversation["updated_at"] = timestamp
            payload["updated_at"] = timestamp
            save_chat_state(PROJECT_ROOT, payload)
            _clear_session_live_output(session_id)
            _persist_chat_turn_work_run(
                session_id=session_id,
                turn_id=str(context.get("turn_id") or ""),
                status="failed",
                summary=work_run_summary,
                error_type=error_type,
                error=raw_error,
                finished_at=timestamp,
                updated_at=timestamp,
            )
            _record_session_turn_result_log(
                session_id,
                str(context.get("turn_id") or ""),
                status="failed_provider",
                summary=work_run_summary,
                recovery_pointer={"resumeAllowed": True, "source": "provider_failure"},
            )
            _record_session_turn_lifecycle_event(
                session_id,
                "failure_persisted",
                turn_id=str(context.get("turn_id") or ""),
                level="error",
                outcome="failed",
                fields={
                    "errorType": error_type,
                    "providerFailure": True,
                    "messageCount": len(messages),
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
                turn_id=str(context.get("turn_id") or ""),
                error_type=error_type,
                raw_error=raw_error,
                related_event_code="conversation.turn_error",
            )
            return
        assistant_entry = _make_chat_message("assistant", summary)
        conversation["messages"] = messages + [assistant_entry]
        conversation.pop("last_turn_error", None)
        conversation.pop("lastTurnError", None)
        conversation["last_turn_status"] = "failed"
        conversation["updated_at"] = assistant_entry["timestamp"]
        payload["updated_at"] = assistant_entry["timestamp"]
        save_chat_state(PROJECT_ROOT, payload)
        _clear_session_live_output(session_id)
        _persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=str(context.get("turn_id") or ""),
            status="failed",
            summary=work_run_summary,
            error_type=error_type,
            error=raw_error,
            finished_at=assistant_entry["timestamp"],
            updated_at=assistant_entry["timestamp"],
        )
        _record_session_turn_visible_message(
            session_id,
            str(context.get("turn_id") or ""),
            assistant_entry,
            event="assistant_failure",
            status="failed",
        )
        _record_session_turn_result_log(
            session_id,
            str(context.get("turn_id") or ""),
            status="failed_runtime",
            summary=work_run_summary,
            recovery_pointer={"resumeAllowed": True, "source": "runtime_failure"},
        )
        _record_session_turn_lifecycle_event(
            session_id,
            "failure_persisted",
            turn_id=str(context.get("turn_id") or ""),
            level="error",
            outcome="failed",
            fields={
                "errorType": error_type,
                "providerFailure": False,
                "messageCount": len(conversation.get("messages") or []),
                "assistantTextLength": len(str(assistant_entry.get("content") or "")),
            },
        )
    _record_session_cycle_message(
        session_id,
        assistant_entry,
        event="assistant_failure",
        status="failed",
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
    metadata: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
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
    normalized_attachments = _normalize_message_attachments(attachments or [])
    if normalized_attachments:
        message["attachments"] = normalized_attachments
    if isinstance(metadata, dict) and metadata:
        message["metadata"] = dict(metadata)
    return message


def _format_agent_inbox_wake_prompt(message: dict[str, Any]) -> str:
    source_code = str(message.get("sourceAgentCode") or "").strip()
    source_name = str(message.get("sourceAgentName") or "").strip()
    source_agent_id = str(message.get("sourceAgentId") or "").strip()
    source_label = " · ".join(item for item in (source_code, source_name) if item) or source_agent_id or "外部来源"
    content = trim_lines(str(message.get("content") or ""), max_lines=20)
    summary = trim_lines(str(message.get("summary") or ""), max_lines=4)
    lines = [
        "[Agent 私信]",
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
            "请基于你的身份、当前会话上下文和可用信息回复这条来自其他 Agent 的消息。",
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


def _record_session_agent_binding_updated_event(
    session_id: str,
    *,
    agent_id: str,
    profile_id: str,
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
                "profileId": _normalize_session_agent_profile_id(profile_id),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "profile_id": _normalize_session_agent_profile_id(profile_id),
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
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_missing",
            "session.agent_missing.hidden_from_index",
            level="warning",
            outcome="hidden",
            message="Session hidden from indexes because its bound Agent is missing or archived.",
            fields={
                "sessionId": session_id,
                "agentId": str(summary.get("agentId") or "").strip(),
                "agentStatusCode": agent_status_code,
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": session_id,
                "agent_id": str(summary.get("agentId") or "").strip(),
                "agent_status_code": agent_status_code,
                "agent_status_message": trim_lines(str(summary.get("agentStatusMessage") or ""), max_lines=2),
                "source": str(source or "").strip(),
                "hidden_from_index": True,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_directory_conversation_index_event(
    agent: dict[str, Any],
    *,
    session_id: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "agent_directory_index",
            "session.agent_directory_index_added",
            level="info",
            outcome="indexed",
            message="Agent Directory direct session added to the conversation index.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
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


def _record_session_agent_profile_repaired_event(
    session_id: str,
    *,
    agent_id: str,
    previous_profile_id: str,
    profile_id: str,
    prompt_template_id: str = "",
    role_key: str = "",
) -> None:
    normalized_session_id = str(session_id or "").strip()
    try:
        record_runtime_scene_event(
            "conversation",
            "session_agent_profile_repaired",
            "session.agent_profile_repaired",
            level="info",
            outcome="repaired",
            message="Session legacy Agent profile repaired from AgentInstance.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "previousProfileId": _normalize_session_agent_profile_id(previous_profile_id),
                "profileId": _normalize_session_agent_profile_id(profile_id),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": "AgentInstance",
            },
            child_log_path=f"conversations/{_safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "previous_profile_id": _normalize_session_agent_profile_id(previous_profile_id),
                "profile_id": _normalize_session_agent_profile_id(profile_id),
                "prompt_template_id": str(prompt_template_id or "").strip(),
                "role_key": str(role_key or "").strip(),
                "source": "AgentInstance",
                "action": "profile_repaired",
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
            message="Historical user message edited and resubmitted.",
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
    if status in {"running", "pending", "done", "success", "failed", "error", "blocked"}:
        if status == "success":
            return "done"
        if status == "error":
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


def _normalize_session_turn_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    message = trim_lines(value.get("message") or value.get("summary") or "", max_lines=4)
    if not message:
        return None
    return {
        "message": message,
        "errorType": str(value.get("errorType") or value.get("error_type") or "runtime_error").strip() or "runtime_error",
        "recoverable": bool(value.get("recoverable", True)),
        "timestamp": str(value.get("timestamp") or value.get("createdAt") or value.get("created_at") or "").strip(),
        "turnId": str(value.get("turnId") or value.get("turn_id") or "").strip(),
    }


def _make_session_turn_error(raw_error: Any, *, lang: str, error_type: str = "", turn_id: str = "") -> dict[str, Any]:
    normalized_error_type = str(error_type or _failure_error_type(str(raw_error or ""))).strip() or "runtime_error"
    return {
        "message": _user_visible_failure_summary(raw_error, lang=lang),
        "error_type": normalized_error_type,
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


def _is_provider_failed_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
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
    candidates = [
        result.get("error"),
        result.get("raw_error"),
        result.get("rawError"),
        result.get("summary"),
        result.get("raw_output"),
        result.get("message"),
        result.get("blocked_reason"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if _looks_like_provider_error_text(text):
            return text
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


def _user_visible_failure_summary(raw_error: Any, *, lang: str | None = None, exc: Exception | None = None) -> str:
    language = lang or get_web_language()
    text = str(raw_error or "").strip()
    if _looks_like_provider_error_text(text):
        return text_for(
            language,
            zh="模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            en='The model provider failed upstream, so this turn did not complete. The full provider error was written to runtime logs; retry later or send "continue".',
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
) -> dict[str, Any] | None:
    if not _is_mental_model_enabled_for_turn(mental_model_enabled):
        return None
    state_snapshot = None
    if isinstance(result, dict):
        explicit = _normalize_mental_snapshot(result.get("mental_snapshot") or result.get("mentalSnapshot"))
        if _has_meaningful_mental_snapshot(explicit):
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

    if _has_meaningful_mental_snapshot(runtime_snapshot):
        merged = dict(runtime_snapshot)
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
    if _has_meaningful_mental_snapshot(state_snapshot):
        return state_snapshot
    if _has_meaningful_mental_snapshot(diagnosis_snapshot):
        return diagnosis_snapshot
    return None


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
    detail_messages = list(messages or [])
    live_message = _build_live_output_message(session_id)
    if live_message is None:
        return detail_messages
    return detail_messages + [live_message]


def _build_live_output_message(session_id: str) -> dict[str, Any] | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        stage = str(state.stage or "").strip()
        thought = str(state.thought or "").strip()
        content = str(state.content or "").strip()
        mental_snapshot = _normalize_mental_snapshot(state.mental_snapshot)
        tool_calls = _normalize_message_tool_calls(state.tool_calls)
        timestamp = str(state.updated_at or "").strip() or _now_timestamp()
    if not thought and not content and mental_snapshot is None and not tool_calls:
        return None
    message: dict[str, Any] = {
        "id": f"{session_id}-message-live",
        "role": "assistant",
        "content": content,
        "timestamp": timestamp,
        "streaming": True,
    }
    if stage:
        message["streamStage"] = stage
    if thought:
        message["thought"] = thought
    if mental_snapshot is not None:
        message["mentalSnapshot"] = mental_snapshot
    if tool_calls:
        message["toolCalls"] = tool_calls
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
) -> None:
    requested_turn_id = str(turn_id or "").strip()
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
        if stage is not _UNSET:
            state.stage = str(stage or "").strip()
        if thought is not _UNSET:
            state.thought = _sanitize_thought_text(thought)
        if content is not _UNSET:
            state.content = _sanitize_message_content("assistant", content)
        if mental_snapshot is not _UNSET:
            state.mental_snapshot = _normalize_mental_snapshot(mental_snapshot)
        if tool_calls is not _UNSET:
            state.tool_calls = _normalize_message_tool_calls(tool_calls)
        state.updated_at = _now_timestamp()
        if not state.thought and not state.content and state.mental_snapshot is None and not state.tool_calls:
            _SESSION_LIVE_OUTPUTS.pop(session_id, None)
    _publish_session_detail_snapshot(session_id)


def _set_session_waiting_live_output(session_id: str, *, turn_id: str = "") -> None:
    _set_session_turn_progress_live_output(session_id, "context_prepare", turn_id=turn_id)


def _set_session_turn_progress_live_output(session_id: str, stage: str, *, turn_id: str = "") -> None:
    language = get_web_language()
    stage_key = str(stage or "").strip().lower()
    labels = {
        "context_prepare": text_for(
            language,
            zh="正在准备对话上下文...",
            en="Preparing the conversation context...",
        ),
        "queued": text_for(
            language,
            zh="当前 Agent 正在处理上一项任务，本轮已进入队列...",
            en="The agent is handling another task. This turn is queued...",
        ),
        "agent_prepare": text_for(
            language,
            zh="正在唤起对话 agent...",
            en="Preparing the conversation agent...",
        ),
        "history_restore": text_for(
            language,
            zh="正在恢复上一轮对话记忆...",
            en="Restoring the previous conversation memory...",
        ),
        "model_request": text_for(
            language,
            zh="正在请求模型，等待首个响应片段...",
            en="Requesting the model and waiting for the first response chunk...",
        ),
        "followup_prepare": text_for(
            language,
            zh="正在准备继续推进下一步...",
            en="Preparing the next continuation step...",
        ),
    }
    content = labels.get(
        stage_key,
        text_for(language, zh="正在等待模型响应...", en="Waiting for the model response..."),
    )
    _set_session_live_output(session_id, turn_id=turn_id, stage=stage_key, content=content)
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


def _clear_session_live_output(session_id: str) -> None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        _SESSION_LIVE_OUTPUTS.pop(session_id, None)


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
    live_mental = _normalize_mental_snapshot(getattr(live_state, "mental_snapshot", None) if live_state else None)
    stop_text = text_for(
        lang,
        zh="本轮已按请求停止。可发送“继续”恢复这次未完成的任务。",
        en='This turn was stopped as requested. Send "continue" to resume the unfinished task.',
    )
    assistant_text = f"{live_content}\n\n{stop_text}".strip() if live_content else stop_text

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
        }
        assistant_entry = _make_chat_message(
            "assistant",
            assistant_text,
            live_tools,
            thought=live_thought,
            mental_snapshot=live_mental,
        )
        if live_tools:
            assistant_entry["toolCalls"] = live_tools
        conversation["messages"] = messages + [assistant_entry]
        next_active_task = _build_session_active_task(
            session_id,
            stopped_result,
            conversation["messages"],
            existing_task=existing_active_task,
        )
        if next_active_task is not None:
            conversation["active_task"] = next_active_task
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
        _set_session_live_output(session_id, turn_id=capture.turn_id, tool_calls=capture.tool_calls)
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

    for event_name in (EventNames.TOOL_START, EventNames.TOOL_SUCCESS, EventNames.TOOL_ERROR):
        callback_ids.append(
            event_bus.subscribe(
                event_name,
                tool_event_proxy,
                callback_id=f"web_chat_{session_id}_{event_name}_{id(capture)}",
            )
        )
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
                _set_session_live_output(session_id, turn_id=capture.turn_id, thought=cleaned)

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
                capture.note_content(cleaned)
                _set_session_live_output(session_id, turn_id=capture.turn_id, content=cleaned)

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
                _set_session_live_output(session_id, turn_id=capture.turn_id, mental_snapshot=snapshot)

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
    if not isinstance(active_task, dict):
        return _build_resume_goal_from_conversation_context(messages, active_task={}), "conversation_context"
    status = str(active_task.get("status") or "").strip().lower()
    if status in {"done", "idle"}:
        return "", ""
    goal = trim_lines(active_task.get("goal") or active_task.get("title") or "", max_lines=2)
    if _is_effective_user_message(goal):
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
    exact_values = {
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
    }
    if compact in exact_values:
        return True
    return bool(
        re.fullmatch(
            r"(好的|好|确认|同意|可以|是的|对的)?(按这个|按计划|就这样)?(开始|继续)(修改|修复|实现|执行|处理|推进)",
            compact,
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
) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return existing_task

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
    last_user_message = _latest_user_message(messages)
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
            "source": "web_session",
            "outcome": outcome,
            "default_file_context": default_file_context,
            "active_preview_path": active_preview_path,
        }
    )
    if blocked_reason:
        metadata["blocked_reason"] = blocked_reason
    if required_user_input:
        metadata["required_user_input"] = required_user_input
    if last_user_message and not _is_effective_user_message(last_user_message):
        metadata["last_user_message_filtered"] = True
        metadata["last_user_message_reason"] = "non_meaningful_user_message"

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
    last_user_message = _latest_user_message(messages)
    if _is_contextual_confirmation_message(last_user_message) and isinstance(hint_active_task, dict):
        hint_goal = trim_lines(hint_active_task.get("goal") or hint_active_task.get("title") or "", max_lines=2)
        if _is_effective_user_message(hint_goal):
            return hint_active_task
    return stored_active_task or hint_active_task


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
    return bool(controller.snapshot().get("stopRequested"))


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


def _publish_session_detail_snapshot(session_id: str) -> None:
    detail = get_session_detail(session_id)
    if detail is None:
        return
    event = {
        "type": "session_detail",
        "sessionId": session_id,
        "detail": detail,
    }
    with _SESSION_STREAM_SUBSCRIBERS_LOCK:
        subscribers = list(_SESSION_STREAM_SUBSCRIBERS.get(session_id) or [])
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(event)
        except queue.Full:
            try:
                subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                continue


def _encode_sse_event(event_name: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"
