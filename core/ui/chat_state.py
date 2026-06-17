# -*- coding: utf-8 -*-
"""chat 模式的轻量状态落盘与恢复。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from core.infrastructure import developer_sandbox
from core.logging import debug as _debug_logger
from core.orchestration.output_boundary import (
    sanitize_assistant_thought_text,
    sanitize_assistant_visible_text,
)


CHAT_STATE_VERSION = 1
DEFAULT_CHAT_CONVERSATION_ID = "default"
DEFAULT_CHAT_CONVERSATION_TITLE = "默认对话"
_CHAT_STATE_THREAD_LOCK = threading.RLock()
_CHAT_STATE_LOCK_STATE = threading.local()


def chat_state_path(project_root: Path) -> Path:
    return developer_sandbox.sandboxed_workspace_path(project_root, "chat", "chat_state.json")


def formal_chat_state_path(project_root: Path) -> Path:
    return developer_sandbox.formal_workspace_path(project_root, "chat", "chat_state.json")


def chat_state_lock_path(project_root: Path) -> Path:
    return chat_state_path(project_root).with_name(".chat_state.lock")


@contextmanager
def chat_state_transaction(project_root: Path):
    """Serialize chat-state load/mutate/save sequences across threads and processes."""

    lock_path = chat_state_lock_path(project_root)
    lock_key = _path_key(lock_path)
    counts: dict[str, int] = getattr(_CHAT_STATE_LOCK_STATE, "counts", {})
    if not hasattr(_CHAT_STATE_LOCK_STATE, "counts"):
        _CHAT_STATE_LOCK_STATE.counts = counts
    if counts.get(lock_key, 0) > 0:
        counts[lock_key] += 1
        try:
            yield
        finally:
            counts[lock_key] -= 1
            if counts[lock_key] <= 0:
                counts.pop(lock_key, None)
        return

    _CHAT_STATE_THREAD_LOCK.acquire()
    handle: BinaryIO | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        _ensure_lock_byte(handle)
        _lock_file(handle)
        counts[lock_key] = 1
        yield
    finally:
        counts.pop(lock_key, None)
        if handle is not None:
            try:
                _unlock_file(handle)
            finally:
                handle.close()
        _CHAT_STATE_THREAD_LOCK.release()


def _path_key(path: Path) -> str:
    raw = str(path.resolve())
    return raw.lower() if os.name == "nt" else raw


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def normalize_chat_tool_calls(value: Any) -> list[str | dict[str, Any]]:
    tool_calls: list[str | dict[str, Any]] = []
    for item in list(value or []):
        name = ""
        if isinstance(item, dict):
            function_block = item.get("function") or {}
            if not isinstance(function_block, dict):
                function_block = {}
            name = str(
                item.get("name")
                or item.get("tool_name")
                or item.get("toolName")
                or function_block.get("name")
                or ""
            ).strip()
            if name:
                normalized: dict[str, Any] = {"name": name}
                for key in (
                    "id",
                    "tool_call_id",
                    "toolCallId",
                    "status",
                    "summary",
                    "arguments",
                    "args",
                    "argKeys",
                    "result",
                    "resultPreview",
                    "result_preview",
                    "resultType",
                    "result_type",
                    "resultLength",
                    "result_length",
                    "error",
                    "durationMs",
                    "duration_ms",
                    "durationSeconds",
                    "duration_seconds",
                    "elapsedSeconds",
                    "timeoutSeconds",
                    "timeout_seconds",
                    "tracePath",
                    "trace_path",
                ):
                    if key in item:
                        normalized[key] = item[key]
                tool_calls.append(normalized)
                continue
        else:
            name = str(item or "").strip()
        if name:
            tool_calls.append(name)
    return tool_calls


def normalize_chat_attachments(value: Any) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifactId") or item.get("artifact_id") or "").strip()
        url = str(item.get("url") or item.get("imageUrl") or item.get("image_url") or "").strip()
        content_type = str(item.get("contentType") or item.get("content_type") or "").strip()
        if not artifact_id and not url:
            continue
        normalized: dict[str, Any] = {
            "artifactId": artifact_id,
            "filename": str(item.get("filename") or artifact_id or "").strip(),
            "url": url,
            "imageUrl": str(item.get("imageUrl") or url).strip(),
            "downloadUrl": str(item.get("downloadUrl") or item.get("download_url") or url).strip(),
            "contentType": content_type,
            "sizeBytes": int(item.get("sizeBytes") or item.get("size_bytes") or 0),
            "kind": str(item.get("kind") or "user_image").strip() or "user_image",
            "status": str(item.get("status") or "ready").strip() or "ready",
        }
        artifact_path = str(item.get("artifactPath") or item.get("artifact_path") or "").strip()
        if artifact_path:
            normalized["artifactPath"] = artifact_path
        attachments.append(normalized)
    return attachments


def normalize_chat_references(value: Any) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("sessionId") or item.get("session_id") or "").strip()
        if not session_id:
            continue
        reference_id = str(item.get("referenceId") or item.get("reference_id") or f"session:{session_id}").strip()
        normalized: dict[str, Any] = {
            "referenceId": reference_id,
            "kind": str(item.get("kind") or "session").strip() or "session",
            "sessionId": session_id,
            "title": str(item.get("title") or session_id).strip(),
            "agentId": str(item.get("agentId") or item.get("agent_id") or "").strip(),
            "agentCode": str(item.get("agentCode") or item.get("agent_code") or "").strip(),
            "agentDisplayName": str(item.get("agentDisplayName") or item.get("agent_display_name") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "createdAt": str(item.get("createdAt") or item.get("created_at") or "").strip(),
        }
        references.append(normalized)
    return references


def normalize_chat_message(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    raw_content = str(item.get("content") or "").strip()
    raw_thought = str(item.get("thought") or "").strip()
    if role == "assistant":
        content = sanitize_assistant_visible_text(raw_content)
        thought = sanitize_assistant_thought_text(raw_thought)
    else:
        content = raw_content
        thought = raw_thought
    mental_snapshot = item.get("mental_snapshot")
    if mental_snapshot is None:
        mental_snapshot = item.get("mentalSnapshot")
    tool_calls = normalize_chat_tool_calls(item.get("tool_calls") or item.get("toolCalls") or item.get("tools") or [])
    feedback_events = item.get("feedback_events") or item.get("feedbackEvents") or []
    if not isinstance(feedback_events, list):
        feedback_events = []
    attachments = normalize_chat_attachments(item.get("attachments") or item.get("imageAttachments") or [])
    metadata = item.get("metadata")
    references = normalize_chat_references(item.get("references") or (metadata if isinstance(metadata, dict) else {}).get("sessionReferences") or [])
    if role == "user" and not content and not attachments and not references:
        return None
    if role == "assistant" and not content and not thought and not isinstance(mental_snapshot, dict) and not tool_calls:
        return None
    timestamp = str(item.get("timestamp") or "").strip() or datetime.now().isoformat(timespec="seconds")
    normalized: dict[str, Any] = {
        "role": role,
        "content": content,
        "timestamp": timestamp,
    }
    if thought:
        normalized["thought"] = thought
    if isinstance(mental_snapshot, dict) and mental_snapshot:
        normalized["mental_snapshot"] = dict(mental_snapshot)
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    if feedback_events:
        normalized["feedback_events"] = [dict(event) for event in feedback_events if isinstance(event, dict)]
    if attachments:
        normalized["attachments"] = attachments
    if references:
        normalized["references"] = references
    if isinstance(metadata, dict) and metadata:
        normalized["metadata"] = dict(metadata)
    return normalized


def normalize_chat_messages(items: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in list(items or []):
        normalized = normalize_chat_message(item)
        if normalized is not None:
            messages.append(normalized)
    return messages


def load_chat_state(project_root: Path) -> dict[str, Any]:
    with chat_state_transaction(project_root):
        path = chat_state_path(project_root)
        if not path.exists() and path != formal_chat_state_path(project_root):
            path = formal_chat_state_path(project_root)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _backup_corrupt_chat_state(path, exc)
            return {}
        return payload if isinstance(payload, dict) else {}


def save_chat_state(project_root: Path, state: dict[str, Any]) -> None:
    with chat_state_transaction(project_root):
        path = chat_state_path(project_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2))


def _backup_corrupt_chat_state(path: Path, exc: Exception) -> None:
    if not path.exists():
        return
    backup_path = path.with_name(f"{path.name}.corrupt.{int(time.time() * 1000)}.json")
    try:
        shutil.copy2(path, backup_path)
        _debug_logger.warning(
            f"[ChatState] chat_state load failed; corrupt file backed up to {backup_path}: {type(exc).__name__}: {exc}"
        )
    except OSError as backup_exc:
        _debug_logger.warning(
            f"[ChatState] chat_state load failed and corrupt backup failed for {path}: "
            f"{type(exc).__name__}: {exc}; backup_error={type(backup_exc).__name__}: {backup_exc}"
        )


def _atomic_write_text(path: Path, payload: str) -> None:
    tmp_path = ""
    fd = -1
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent_dir(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_parent_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def get_active_chat_conversation(state: dict[str, Any]) -> dict[str, Any]:
    conversation_id = str(state.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    conversations = state.get("conversations")
    if not isinstance(conversations, list):
        return {
            "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
            "title": DEFAULT_CHAT_CONVERSATION_TITLE,
            "messages": [],
            "active_task": None,
            "updated_at": "",
        }
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() == conversation_id:
            return {
                "conversation_id": conversation_id,
                "title": str(item.get("title") or DEFAULT_CHAT_CONVERSATION_TITLE),
                "messages": normalize_chat_messages(item.get("messages") or []),
                "active_task": item.get("active_task") if isinstance(item.get("active_task"), dict) else None,
                "updated_at": str(item.get("updated_at") or ""),
            }
    return {
        "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
        "title": DEFAULT_CHAT_CONVERSATION_TITLE,
        "messages": [],
        "active_task": None,
        "updated_at": "",
    }


def build_chat_state(
    messages: list[dict[str, Any]],
    *,
    conversation_id: str = DEFAULT_CHAT_CONVERSATION_ID,
    title: str = DEFAULT_CHAT_CONVERSATION_TITLE,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_messages = normalize_chat_messages(messages)
    updated_at = datetime.now().isoformat(timespec="seconds")
    return {
        "version": CHAT_STATE_VERSION,
        "active_conversation_id": conversation_id,
        "updated_at": updated_at,
        "conversations": [
            {
                "conversation_id": conversation_id,
                "title": title,
                "updated_at": updated_at,
                "messages": normalized_messages,
                "active_task": dict(active_task or {}) if isinstance(active_task, dict) and active_task else None,
            }
        ],
    }
