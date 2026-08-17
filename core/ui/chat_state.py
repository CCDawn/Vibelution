# -*- coding: utf-8 -*-
"""chat 模式的轻量状态落盘与恢复。"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Callable

from core.infrastructure import developer_sandbox
from core.chat.session_catalog import (
    CATALOG_GLOBAL_DIRTY_SESSION_ID,
    notify_session_catalog_dirty,
)
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
                    "callId",
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
    """Load the canonical compatibility document from ConversationStore.

    ``chat_state.json`` is consulted only when the SQLite root row does not
    exist yet, in which case it is transactionally imported with a timestamped
    backup. Normal runtime reads never parse the legacy JSON file.
    """

    with chat_state_transaction(project_root):
        with _chat_state_repository(project_root) as repository:
            payload = repository.get_chat_state()
            if payload:
                return payload
            path = _legacy_chat_state_source_path(project_root)
            if path is None:
                return {}
            try:
                from core.chat.conversation_store import LegacyChatStateImporter

                LegacyChatStateImporter(repository).import_file(
                    path,
                    project_root=project_root,
                )
            except Exception as exc:
                if isinstance(exc, (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError)):
                    _backup_corrupt_chat_state(path, exc)
                    return {}
                raise
            return repository.get_chat_state()


def save_chat_state(
    project_root: Path,
    state: dict[str, Any],
    *,
    archive_session_id: str = "",
    expected_state_revision: int | None = None,
) -> None:
    with chat_state_transaction(project_root):
        cleaned, _changed = _drop_legacy_chat_state_messages(state, project_root=project_root)
        normalized_archive_session_id = str(archive_session_id or "").strip()
        with _chat_state_repository(project_root) as repository:
            if normalized_archive_session_id:
                combined = repository.archive_session_and_replace_chat_state(
                    session_id=normalized_archive_session_id,
                    state=cleaned,
                    expected_state_revision=expected_state_revision,
                ).result(timeout=5)
                result = dict(combined.get("chatState") or {})
            else:
                result = repository.replace_chat_state(
                    cleaned,
                    expected_state_revision=expected_state_revision,
                ).result(timeout=5)
        revision = int(result.get("stateRevision") or 0)
        cleaned["state_revision"] = revision
        notify_session_catalog_dirty(
            project_root,
            CATALOG_GLOBAL_DIRTY_SESSION_ID,
            f"state:{revision}",
        )


def mutate_chat_state(
    project_root: Path,
    mutate: Callable[[dict[str, Any]], Any],
    *,
    expected_state_revision: int | None = None,
) -> dict[str, Any]:
    """Atomically read-modify-write the chat state inside one store transaction.

    ``mutate`` receives the current document and runs on the writer thread;
    it must be deterministic, must not submit other store work, and must not
    block for a long time. Concurrent updates are never overwritten because
    every mutation reads the freshest revision inside the transaction.
    """

    with chat_state_transaction(project_root):
        with _chat_state_repository(project_root) as repository:
            result = repository.update_chat_state(
                mutate,
                expected_state_revision=expected_state_revision,
            ).result(timeout=5)
        revision = int(result.get("stateRevision") or 0)
        notify_session_catalog_dirty(
            project_root,
            CATALOG_GLOBAL_DIRTY_SESSION_ID,
            f"state:{revision}",
        )
        return result


def load_session_chat_state(project_root: Path, session_id: str) -> dict[str, Any] | None:
    """Load one session runtime row without assembling the compatibility document."""

    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    with _chat_state_repository(project_root) as repository:
        return repository.get_session_runtime_state(normalized)


def list_session_runtime_ids(project_root: Path) -> list[str]:
    """List session runtime ids without assembling conversation payloads."""

    with _chat_state_repository(project_root) as repository:
        return list(repository.list_session_runtime_ids())


def load_active_conversation_id(project_root: Path) -> str:
    """Load the workspace active session id without assembling conversations."""

    with _chat_state_repository(project_root) as repository:
        return str(repository.get_active_session_id() or "").strip()


def save_session_chat_state(
    project_root: Path,
    session_id: str,
    conversation: dict[str, Any],
    *,
    activate: bool = False,
) -> None:
    """Persist one session runtime row without rewriting sibling sessions."""

    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("Session runtime state requires a session id.")
    cleaned, _changed = _drop_legacy_chat_state_messages(
        {"conversations": [dict(conversation)]},
        project_root=project_root,
    )
    conversations = cleaned.get("conversations") if isinstance(cleaned, dict) else []
    payload = dict(conversations[0]) if conversations and isinstance(conversations[0], dict) else dict(conversation)
    payload.setdefault("conversation_id", normalized)
    payload.setdefault("conversationId", normalized)
    with chat_state_transaction(project_root):
        with _chat_state_repository(project_root) as repository:
            result = repository.upsert_session_runtime_state(
                normalized,
                payload,
                activate=activate,
            ).result(timeout=5)
    revision = int((result or {}).get("stateRevision") or 0)
    notify_session_catalog_dirty(
        project_root,
        normalized,
        f"state:{revision}",
    )
    if activate:
        notify_session_catalog_dirty(
            project_root,
            CATALOG_GLOBAL_DIRTY_SESSION_ID,
            f"state:{revision}",
        )


@contextmanager
def _chat_state_repository(project_root: Path):
    """Yield the process store repository or a bounded standalone store."""

    from core.web.services.session import directory_runtime

    root = Path(project_root).resolve()
    store = directory_runtime.get_open_directory_store()
    if store is not None and directory_runtime.directory_store_project_root() == root:
        yield store.repository
        return

    from core.chat.conversation_store import ConversationStore

    standalone = ConversationStore(directory_runtime.conversation_store_path(root))
    standalone.open()
    try:
        yield standalone.repository
    finally:
        standalone.close()


def _legacy_chat_state_source_path(project_root: Path) -> Path | None:
    path = chat_state_path(project_root)
    if not path.exists() and path != formal_chat_state_path(project_root):
        path = formal_chat_state_path(project_root)
    return path if path.exists() else None


def _drop_legacy_chat_state_messages(
    state: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    if not isinstance(state, dict):
        return {}, True
    changed = False
    cleaned = dict(state)
    conversations = cleaned.get("conversations")
    if isinstance(conversations, list):
        cleaned_conversations: list[Any] = []
        for item in conversations:
            if not isinstance(item, dict):
                cleaned_conversations.append(item)
                continue
            conversation = dict(item)
            if "messages" not in conversation:
                cleaned_conversations.append(conversation)
                continue
            if project_root is None:
                cleaned_conversations.append(conversation)
                continue
            try:
                materialized = _materialize_legacy_messages_into_ledger(project_root, conversation)
            except Exception as exc:
                _debug_logger.warning(
                    f"[ChatState] legacy message materialize failed: {type(exc).__name__}: {exc}"
                )
                cleaned_conversations.append(conversation)
                continue
            if not materialized:
                cleaned_conversations.append(conversation)
                continue
            conversation.pop("messages", None)
            conversation.pop("legacy_messages_preserved", None)
            conversation.pop("legacyMessagesPreserved", None)
            changed = True
            cleaned_conversations.append(conversation)
        if changed:
            cleaned["conversations"] = cleaned_conversations
    return cleaned, changed


def _conversation_session_id(conversation: dict[str, Any]) -> str:
    return str(
        conversation.get("conversation_id")
        or conversation.get("conversationId")
        or conversation.get("id")
        or ""
    ).strip()


def _materialize_legacy_messages_into_ledger(project_root: Path, conversation: dict[str, Any]) -> bool:
    session_id = _conversation_session_id(conversation)
    if not session_id:
        return False
    from core.chat.conversation_ledger import (
        EVENT_ASSISTANT_MESSAGE,
        EVENT_USER_MESSAGE,
        append_conversation_event,
        load_conversation_events,
    )

    turn_id = "legacy-chat-state-import"
    existing = load_conversation_events(Path(project_root), session_id)
    legacy_existing = [
        event
        for event in existing
        if event.turn_id == turn_id
        and event.source == "legacy_chat_state_import"
        and event.source_kind == "legacy_import"
        and event.event_type in {EVENT_USER_MESSAGE, EVENT_ASSISTANT_MESSAGE}
    ]
    raw_messages = conversation.get("messages")
    if not isinstance(raw_messages, list):
        return bool(existing) and not legacy_existing

    expected: list[tuple[str, str, str]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            return False
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            return False
        content = str(item.get("content") or "")
        event_type = EVENT_USER_MESSAGE if role == "user" else EVENT_ASSISTANT_MESSAGE
        expected.append((event_type, content, str(item.get("timestamp") or "").strip()))

    if existing and not legacy_existing:
        # A canonical ledger already owns this session. Never let the leftover
        # blob overwrite or append behind it.
        return True
    if len(legacy_existing) != len(existing) or len(legacy_existing) > len(expected):
        # A partial legacy prefix mixed with other facts is ambiguous. Keep the
        # source blob so an operator can reconcile it without losing messages.
        return False

    declared_total: int | None = None
    complete_markers = bool(legacy_existing)
    marker_prefix = "legacy-chat-state-import:"
    for position, event in enumerate(legacy_existing, start=1):
        marker = str(event.correlation_id or "")
        if not marker.startswith(marker_prefix):
            complete_markers = False
            break
        try:
            ordinal_text, total_text = marker.removeprefix(marker_prefix).split("/", 1)
            ordinal = int(ordinal_text)
            total = int(total_text)
        except (TypeError, ValueError):
            complete_markers = False
            break
        if (
            ordinal != position
            or total < position
            or (declared_total is not None and total != declared_total)
        ):
            complete_markers = False
            break
        declared_total = total
    if complete_markers and declared_total is not None:
        if len(legacy_existing) == declared_total:
            # This ledger already completed an earlier import. A leftover blob
            # reappearing later must not replace or extend canonical history.
            return True
        if declared_total != len(expected):
            return False

    for index, event in enumerate(legacy_existing):
        expected_type, expected_content, expected_timestamp = expected[index]
        if event.event_type != expected_type or str(event.payload.get("content") or "") != expected_content:
            return False
        if expected_timestamp and event.timestamp != expected_timestamp:
            return False

    for index, (event_type, content, timestamp) in enumerate(
        expected[len(legacy_existing):],
        start=len(legacy_existing),
    ):
        append_conversation_event(
            Path(project_root),
            session_id,
            turn_id,
            event_type,
            status="recorded" if event_type == EVENT_USER_MESSAGE else "completed",
            payload={"content": content},
            source="legacy_chat_state_import",
            timestamp=timestamp,
            correlation_id=f"legacy-chat-state-import:{index + 1}/{len(expected)}",
            source_kind="legacy_import",
        )
    return True


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


def get_active_chat_conversation(state: dict[str, Any]) -> dict[str, Any]:
    conversation_id = str(state.get("active_conversation_id") or DEFAULT_CHAT_CONVERSATION_ID).strip()
    conversations = state.get("conversations")
    if not isinstance(conversations, list):
        return {
            "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
            "title": DEFAULT_CHAT_CONVERSATION_TITLE,
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
                "active_task": item.get("active_task") if isinstance(item.get("active_task"), dict) else None,
                "updated_at": str(item.get("updated_at") or ""),
            }
    return {
        "conversation_id": conversation_id or DEFAULT_CHAT_CONVERSATION_ID,
        "title": DEFAULT_CHAT_CONVERSATION_TITLE,
        "active_task": None,
        "updated_at": "",
    }


def build_chat_state(
    messages: list[dict[str, Any]] | None = None,
    *,
    conversation_id: str = DEFAULT_CHAT_CONVERSATION_ID,
    title: str = DEFAULT_CHAT_CONVERSATION_TITLE,
    active_task: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
                "active_task": dict(active_task or {}) if isinstance(active_task, dict) and active_task else None,
                "conversation_index_kind": "user_chat",
                "conversationIndexKind": "user_chat",
            }
        ],
    }
