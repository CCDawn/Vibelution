"""Agent-linked session lifecycle helpers.

Claim scope: agent session purge/archive/delete/reset, child sessions,
inbox wake/recovery, and CLI agent lifecycle/task-result bridging.

Stop-turn control lives in ``control.py``. Late-bound facade keeps
monkeypatches stable.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import hashlib
import os
from pathlib import Path
from typing import Any, Callable


def _service():
    from core.web.services import session_service

    return session_service


def stage_agent_session_purge(
    agent_id: str,
    *,
    direct_session_id: str = "",
) -> dict[str, Any]:
    """Remove Agent-owned session state and return the token required to finish or roll back."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    normalized_direct_session_id = str(direct_session_id or "").strip()
    if not normalized_agent_id:
        raise s.SessionValidationError("Agent id is required to purge sessions.")
    registered_agent = s.agent_directory_service.get_agent(
        normalized_agent_id,
        include_archived=True,
    )
    if registered_agent is None:
        raise s.SessionNotFoundError(f"Agent not found: {normalized_agent_id}")
    if str(registered_agent.get("status") or "active").strip() != "archived":
        raise s.SessionValidationError(
            "Only archived Agents can have their sessions permanently purged."
        )
    registered_direct_session_id = str(
        registered_agent.get("directSessionId") or ""
    ).strip()
    if (
        normalized_direct_session_id
        and registered_direct_session_id
        and normalized_direct_session_id != registered_direct_session_id
    ):
        raise s.SessionValidationError(
            "Requested direct session does not match the archived Agent."
        )
    normalized_direct_session_id = (
        normalized_direct_session_id or registered_direct_session_id
    )
    s._ensure_agent_direct_session_not_reassigned(
        normalized_agent_id,
        normalized_direct_session_id,
    )
    timestamp = s._now_timestamp()
    restore_token: dict[str, Any] | None = None
    session_ids: list[str] = []
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        session_ids = s._agent_session_conversation_ids(
            conversations,
            agent_id=normalized_agent_id,
            direct_session_id=normalized_direct_session_id,
        )
        selected = set(session_ids)
        for raw in conversations:
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("conversation_id") or "").strip()
            if session_id not in selected:
                continue
            normalized = s._normalize_conversation(
                raw,
                agent_by_id=s._agent_lookup_for_conversations(),
                ensure_workspace=False,
                lightweight=True,
            ) or {"id": session_id}
            phase = s._conversation_phase(session_id, normalized)
            if phase in {"queued", "running", "stopping", "paused"}:
                raise s.SessionBusyError(
                    s.text_for(
                        s.get_web_language(),
                        zh=f"会话 {session_id} 仍在运行或停止中，暂时不能彻底删除 Agent。",
                        en=f"Session {session_id} is still running or stopping; the Agent cannot be purged yet.",
                    )
                )
        restore_token = s._agent_session_lifecycle_restore_token(
            payload,
            agent_id=normalized_agent_id,
            session_ids=session_ids,
        )
        payload["conversations"] = [
            raw
            for raw in conversations
            if not isinstance(raw, dict)
            or str(raw.get("conversation_id") or "").strip() not in selected
        ]
        if str(payload.get("active_conversation_id") or "").strip() in selected:
            existing_session_ids = {
                str(raw.get("conversation_id") or "").strip()
                for raw in conversations
                if isinstance(raw, dict)
            }
            replacement_id = s._replacement_session_after_agent_session_removal(
                payload,
                removed_session_ids=selected,
                timestamp=timestamp,
            )
            payload["active_conversation_id"] = replacement_id
            if restore_token is not None and replacement_id not in existing_session_ids:
                restore_token["createdReplacementSessionId"] = replacement_id
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = timestamp
        s.save_chat_state(s.PROJECT_ROOT, payload)

    staging_roots: list[Path] = []
    workspace_moves: list[dict[str, str]] = []
    try:
        for session_id in session_ids:
            s._set_session_running(session_id, False)
            s._clear_session_turn_control(session_id)
            s._clear_session_live_output(session_id)
            s._invalidate_session_agent_runtime_cache(session_id)
            s._invalidate_session_conversation_events_cache(session_id)

        staging_nonce = s.secrets.token_hex(6)
        workspace_roots = s._agent_session_workspace_roots()
        staging_roots = [
            s._agent_session_purge_staging_root(
                sessions_root,
                agent_id=normalized_agent_id,
                nonce=staging_nonce,
            )
            for sessions_root in workspace_roots
        ]
        for sessions_root, staging_root in zip(
            workspace_roots,
            staging_roots,
            strict=True,
        ):
            root_workspace_moves: list[dict[str, str]] = []
            for session_id in session_ids:
                source = (sessions_root / s._safe_session_workspace_token(session_id)).resolve()
                if not source.is_relative_to(sessions_root) or not source.exists():
                    continue
                staging_root.mkdir(parents=True, exist_ok=True)
                destination = (staging_root / source.name).resolve()
                if not destination.is_relative_to(staging_root):
                    raise s.SessionValidationError(f"Invalid staged session workspace path: {destination}")
                move = {"source": str(source), "staged": str(destination)}
                root_workspace_moves.append(move)
                workspace_moves.append(move)
                s._write_agent_session_purge_manifest(
                    staging_root,
                    {
                        "version": 1,
                        "transactionId": staging_nonce,
                        "agentId": normalized_agent_id,
                        "state": "staged",
                        "sessionIds": session_ids,
                        "workspaceMoves": root_workspace_moves,
                        "updatedAt": s._now_timestamp(),
                    },
                )
                shutil.move(str(source), str(destination))
    except Exception as exc:
        rollback_failures: list[str] = []
        for move in reversed(workspace_moves):
            try:
                s._restore_staged_agent_workspace_move(move)
            except Exception as rollback_error:
                rollback_failures.append(
                    "rollback_workspace:"
                    + type(rollback_error).__name__
                )
        if restore_token is not None:
            try:
                s._restore_agent_session_lifecycle_state(restore_token)
            except Exception as rollback_error:
                rollback_failures.append(
                    "rollback_chat_state:"
                    + type(rollback_error).__name__
                )
        if not rollback_failures:
            for staging_root in staging_roots:
                try:
                    if staging_root.exists():
                        s._delete_agent_session_purge_staging_root(staging_root)
                except Exception as rollback_error:
                    rollback_failures.append(
                        "rollback_staging_cleanup:"
                        + type(rollback_error).__name__
                    )
        if rollback_failures:
            exc.add_note(
                "Agent session purge staging compensation incomplete: "
                + ", ".join(rollback_failures)
            )
        raise
    if restore_token is not None:
        restore_token["workspaceMoves"] = workspace_moves
        restore_token["stagingRoot"] = str(staging_roots[0]) if staging_roots else ""
        restore_token["stagingRoots"] = [str(path) for path in staging_roots]
    s._invalidate_session_list_cache()
    result = {
        "status": "staged",
        "agentId": normalized_agent_id,
        "deletedCount": len(session_ids),
        "sessionIds": session_ids,
        "workspaceStagedCount": len(workspace_moves),
        "workspaceDeletedCount": 0,
        "historyRetention": "deleted",
    }
    if restore_token is not None:
        result["restoreToken"] = restore_token
        result["stagingRoot"] = str(staging_roots[0]) if staging_roots else ""
        result["stagingRoots"] = [str(path) for path in staging_roots]
    s._record_agent_session_lifecycle_event(
        "agent_purge",
        "conversation.agent_sessions.purge_staged",
        fields={
            "agentId": normalized_agent_id,
            "deletedSessionCount": len(session_ids),
            "workspaceStagedCount": len(workspace_moves),
            "sessionIds": session_ids[:20],
        },
    )
    return result


def commit_staged_agent_session_purge(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    token = restore_token if isinstance(restore_token, dict) else {}
    staging_root_values = list(token.get("stagingRoots") or [])
    if not staging_root_values and str(token.get("stagingRoot") or "").strip():
        staging_root_values = [str(token.get("stagingRoot") or "").strip()]
    workspace_moves = [
        item
        for item in list(token.get("workspaceMoves") or [])
        if isinstance(item, dict)
    ]
    allowed_roots = s._agent_session_workspace_roots()
    cleanup_failure_types: list[str] = []
    cleanup_marker_paths: list[Path] = []
    for staging_root_value in staging_root_values:
        staging_root = Path(os.path.abspath(str(staging_root_value or "")))
        cleanup_marker_path = s._agent_session_purge_cleanup_marker_path(
            staging_root
        )
        cleanup_marker_paths.append(cleanup_marker_path)
        if not s._agent_session_purge_staging_root_is_safe(
            staging_root,
            allowed_roots=allowed_roots,
        ):
            cleanup_failure_types.append("UnsafeStagingPath")
            continue
        if staging_root.exists():
            manifest = s._read_agent_session_purge_manifest(staging_root)
            if manifest is None:
                cleanup_failure_types.append("MissingManifest")
                continue
            committed_manifest = {
                **manifest,
                "state": "cleanup_pending",
                "updatedAt": s._now_timestamp(),
            }
            try:
                if (
                    cleanup_marker_path.is_symlink()
                    or s._path_is_reparse_point(cleanup_marker_path)
                ):
                    raise s.SessionValidationError(
                        "Agent session purge cleanup marker is unsafe."
                    )
                s._write_agent_session_purge_record(
                    cleanup_marker_path,
                    {
                        "version": 1,
                        "state": "cleanup_pending",
                        "stagingRootName": staging_root.name,
                        "agentId": str(token.get("agentId") or "").strip(),
                        "transactionId": str(
                            manifest.get("transactionId") or ""
                        ).strip(),
                        "sessionIds": list(token.get("sessionIds") or []),
                        "updatedAt": s._now_timestamp(),
                    },
                )
                s._write_agent_session_purge_manifest(
                    staging_root,
                    committed_manifest,
                )
                s._delete_agent_session_purge_staging_root(staging_root)
            except Exception as exc:
                cleanup_failure_types.append(type(exc).__name__)
        if not staging_root.exists() and cleanup_marker_path.exists():
            try:
                cleanup_marker_path.unlink()
            except OSError as exc:
                cleanup_failure_types.append(type(exc).__name__)
    pending_workspace_count = sum(
        1
        for move in workspace_moves
        if Path(str(move.get("staged") or "")).exists()
    )
    deleted_workspace_count = max(0, len(workspace_moves) - pending_workspace_count)
    cleanup_marker_pending_count = sum(
        1 for marker_path in cleanup_marker_paths if marker_path.exists()
    )
    cleanup_pending = (
        pending_workspace_count > 0
        or cleanup_marker_pending_count > 0
        or bool(cleanup_failure_types)
    )
    result = {
        "status": "cleanup_pending" if cleanup_pending else "deleted",
        "agentId": str(token.get("agentId") or "").strip(),
        "deletedCount": len(list(token.get("sessionIds") or [])),
        "sessionIds": list(token.get("sessionIds") or []),
        "workspaceDeletedCount": deleted_workspace_count,
        "workspacePendingCount": pending_workspace_count,
        "cleanupMarkerPendingCount": cleanup_marker_pending_count,
        "cleanupPending": cleanup_pending,
        "cleanupFailureTypes": sorted(set(cleanup_failure_types)),
        "historyRetention": "deleted",
    }
    s._record_agent_session_lifecycle_event(
        "agent_purge",
        "conversation.agent_sessions.purged",
        outcome="partial" if cleanup_pending else "succeeded",
        level="warning" if cleanup_pending else "info",
        fields={
            "agentId": result["agentId"],
            "deletedSessionCount": result["deletedCount"],
            "workspaceDeletedCount": result["workspaceDeletedCount"],
            "workspacePendingCount": result["workspacePendingCount"],
            "cleanupPending": result["cleanupPending"],
            "cleanupFailureTypes": result["cleanupFailureTypes"],
            "sessionIds": result["sessionIds"][:20],
        },
    )
    return result


def restore_staged_agent_session_purge(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    token = restore_token if isinstance(restore_token, dict) else {}
    workspace_moves = [
        item
        for item in list(token.get("workspaceMoves") or [])
        if isinstance(item, dict)
    ]
    restored_workspace_count = 0
    rollback_failures: list[str] = []
    for move in reversed(workspace_moves):
        try:
            restored_workspace_count += int(
                s._restore_staged_agent_workspace_move(move)
            )
        except Exception as rollback_error:
            rollback_failures.append(
                "rollback_workspace:"
                + type(rollback_error).__name__
            )
    changed = False
    try:
        changed = s._restore_agent_session_lifecycle_state(token)
    except Exception as rollback_error:
        rollback_failures.append(
            "rollback_chat_state:"
            + type(rollback_error).__name__
        )
    if not rollback_failures:
        staging_root_values = list(token.get("stagingRoots") or [])
        if not staging_root_values and str(token.get("stagingRoot") or "").strip():
            staging_root_values = [str(token.get("stagingRoot") or "").strip()]
        allowed_roots = s._agent_session_workspace_roots()
        for staging_root_value in staging_root_values:
            staging_root = Path(
                os.path.abspath(str(staging_root_value or ""))
            )
            try:
                if not s._agent_session_purge_staging_root_is_safe(
                    staging_root,
                    allowed_roots=allowed_roots,
                ):
                    raise s.SessionValidationError(
                        f"Invalid Agent session purge staging path: {staging_root}"
                    )
                if staging_root.exists():
                    s._delete_agent_session_purge_staging_root(staging_root)
            except Exception as rollback_error:
                rollback_failures.append(
                    "rollback_staging_cleanup:"
                    + type(rollback_error).__name__
                )
    if rollback_failures:
        raise s.SessionValidationError(
            "Agent session purge compensation incomplete: "
            + ", ".join(rollback_failures)
        )
    return {
        "status": "restored" if changed else "unchanged",
        "changed": changed,
        "agentId": str(token.get("agentId") or "").strip(),
        "sessionIds": list(token.get("sessionIds") or []),
        "workspaceRestoredCount": restored_workspace_count,
    }


def retry_pending_agent_session_purge_cleanup() -> dict[str, Any]:
    """Retry deletion of durable Agent purge staging directories."""
    s = _service()

    cleaned_root_count = 0
    pending_root_count = 0
    cleanup_failure_types: list[str] = []
    scanned_root_count = 0
    skipped_active_root_count = 0
    allowed_roots = s._agent_session_workspace_roots()
    for sessions_root in allowed_roots:
        if not sessions_root.exists():
            continue
        cleanup_marked_root_names: set[str] = set()
        for marker_path in sessions_root.iterdir():
            if (
                not marker_path.name.startswith(".agent-purge-")
                or not marker_path.name.endswith(
                    s._AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX
                )
            ):
                continue
            scanned_root_count += 1
            if (
                marker_path.is_symlink()
                or s._path_is_reparse_point(marker_path)
            ):
                pending_root_count += 1
                cleanup_failure_types.append("UnsafeCleanupMarker")
                continue
            marker = s._read_agent_session_purge_cleanup_marker(marker_path)
            staging_root_name = str(
                (marker or {}).get("stagingRootName") or ""
            ).strip()
            if (
                marker is None
                or not staging_root_name.startswith(".agent-purge-")
                or marker_path.name
                != staging_root_name
                + s._AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX
            ):
                pending_root_count += 1
                cleanup_failure_types.append("InvalidCleanupMarker")
                continue
            cleanup_marked_root_names.add(staging_root_name)
            staging_root = Path(
                os.path.abspath(sessions_root / staging_root_name)
            )
            if staging_root.exists():
                if not s._agent_session_purge_staging_root_is_safe(
                    staging_root,
                    allowed_roots=allowed_roots,
                ):
                    pending_root_count += 1
                    cleanup_failure_types.append("UnsafeStagingPath")
                    continue
                try:
                    s._delete_agent_session_purge_staging_root(staging_root)
                except Exception as exc:
                    cleanup_failure_types.append(type(exc).__name__)
            if staging_root.exists():
                pending_root_count += 1
                continue
            try:
                marker_path.unlink()
            except OSError as exc:
                cleanup_failure_types.append(type(exc).__name__)
            if marker_path.exists():
                pending_root_count += 1
            else:
                cleaned_root_count += 1
        for candidate in sessions_root.iterdir():
            if (
                not candidate.name.startswith(".agent-purge-")
                or candidate.name.endswith(
                    s._AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX
                )
                or candidate.name in cleanup_marked_root_names
            ):
                continue
            scanned_root_count += 1
            staging_root = Path(os.path.abspath(candidate))
            if not s._agent_session_purge_staging_root_is_safe(
                staging_root,
                allowed_roots=allowed_roots,
            ):
                pending_root_count += 1
                cleanup_failure_types.append("UnsafeStagingPath")
                continue
            manifest = s._read_agent_session_purge_manifest(staging_root)
            if manifest is None:
                pending_root_count += 1
                cleanup_failure_types.append("MissingManifest")
                continue
            if str(manifest.get("state") or "").strip() == "cleanup_pending":
                pending_root_count += 1
                cleanup_failure_types.append("MissingCleanupMarker")
                continue
            skipped_active_root_count += 1
    result = {
        "status": "cleanup_pending" if pending_root_count else "clean",
        "scannedRootCount": scanned_root_count,
        "cleanedRootCount": cleaned_root_count,
        "pendingRootCount": pending_root_count,
        "skippedActiveRootCount": skipped_active_root_count,
        "cleanupFailureTypes": sorted(set(cleanup_failure_types)),
    }
    s._record_agent_session_lifecycle_event(
        "agent_purge",
        "conversation.agent_sessions.purge_cleanup_retried",
        outcome="partial" if pending_root_count else "succeeded",
        level="warning" if pending_root_count else "info",
        fields=result,
    )
    return result


def agent_session_purge_cleanup_failure_result(
    restore_token: dict[str, Any] | None,
    error: Exception,
) -> dict[str, Any]:
    """Describe post-purge cleanup failure without misreporting irreversible delete."""
    s = _service()

    token = restore_token if isinstance(restore_token, dict) else {}
    workspace_moves = [
        item
        for item in list(token.get("workspaceMoves") or [])
        if isinstance(item, dict)
    ]
    cleanup_failure_types = [type(error).__name__]
    staging_root_values = list(token.get("stagingRoots") or [])
    if not staging_root_values and str(token.get("stagingRoot") or "").strip():
        staging_root_values = [str(token.get("stagingRoot") or "").strip()]
    allowed_roots = s._agent_session_workspace_roots()
    cleanup_marker_paths: list[Path] = []
    for staging_root_value in staging_root_values:
        staging_root = Path(os.path.abspath(str(staging_root_value or "")))
        cleanup_marker_path = s._agent_session_purge_cleanup_marker_path(
            staging_root
        )
        cleanup_marker_paths.append(cleanup_marker_path)
        try:
            if not staging_root.exists():
                continue
            if not s._agent_session_purge_staging_root_is_safe(
                staging_root,
                allowed_roots=allowed_roots,
            ):
                raise s.SessionValidationError(
                    "Agent session purge staging path is unsafe."
                )
            manifest = s._read_agent_session_purge_manifest(staging_root)
            if manifest is None:
                raise s.SessionValidationError(
                    "Agent session purge staging manifest is missing."
                )
            if (
                cleanup_marker_path.is_symlink()
                or s._path_is_reparse_point(cleanup_marker_path)
            ):
                raise s.SessionValidationError(
                    "Agent session purge cleanup marker is unsafe."
                )
            s._write_agent_session_purge_record(
                cleanup_marker_path,
                {
                    "version": 1,
                    "state": "cleanup_pending",
                    "stagingRootName": staging_root.name,
                    "agentId": str(token.get("agentId") or "").strip(),
                    "transactionId": str(
                        manifest.get("transactionId") or ""
                    ).strip(),
                    "sessionIds": list(token.get("sessionIds") or []),
                    "updatedAt": s._now_timestamp(),
                },
            )
        except Exception as marker_error:
            cleanup_failure_types.append(
                "cleanup_marker:" + type(marker_error).__name__
            )
    pending_workspace_count = sum(
        1
        for move in workspace_moves
        if Path(str(move.get("staged") or "")).exists()
    )
    cleanup_marker_pending_count = sum(
        1 for marker_path in cleanup_marker_paths if marker_path.exists()
    )
    result = {
        "status": "cleanup_pending",
        "agentId": str(token.get("agentId") or "").strip(),
        "deletedCount": len(list(token.get("sessionIds") or [])),
        "sessionIds": list(token.get("sessionIds") or []),
        "workspaceDeletedCount": max(
            0,
            len(workspace_moves) - pending_workspace_count,
        ),
        "workspacePendingCount": pending_workspace_count,
        "cleanupMarkerPendingCount": cleanup_marker_pending_count,
        "cleanupPending": True,
        "cleanupFailureTypes": sorted(set(cleanup_failure_types)),
        "historyRetention": "deleted",
    }
    s._record_agent_session_lifecycle_event(
        "agent_purge",
        "conversation.agent_sessions.purge_cleanup_failed_after_agent_delete",
        outcome="partial",
        level="warning",
        fields={
            "agentId": result["agentId"],
            "deletedSessionCount": result["deletedCount"],
            "workspacePendingCount": result["workspacePendingCount"],
            "cleanupFailureTypes": result["cleanupFailureTypes"],
            "sessionIds": result["sessionIds"][:20],
        },
    )
    return result


def archive_agent_sessions(
    agent_id: str,
    *,
    direct_session_id: str = "",
    include_restore_token: bool = False,
) -> dict[str, Any]:
    """Seal every Agent-owned session as hidden read-only history."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    normalized_direct_session_id = str(direct_session_id or "").strip()
    if not normalized_agent_id:
        raise s.SessionValidationError("Agent id is required to archive sessions.")
    s._ensure_agent_direct_session_not_reassigned(
        normalized_agent_id,
        normalized_direct_session_id,
    )
    timestamp = s._now_timestamp()
    restore_token: dict[str, Any] | None = None
    session_ids: list[str] = []
    child_count = 0
    direct_count = 0
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        session_ids = s._agent_session_conversation_ids(
            conversations,
            agent_id=normalized_agent_id,
            direct_session_id=normalized_direct_session_id,
        )
        selected = set(session_ids)
        for raw in conversations:
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("conversation_id") or "").strip()
            if session_id not in selected:
                continue
            normalized = s._normalize_conversation(
                raw,
                agent_by_id=s._agent_lookup_for_conversations(),
                ensure_workspace=False,
                lightweight=True,
            ) or {"id": session_id}
            phase = s._conversation_phase(session_id, normalized)
            if phase in {"queued", "running", "stopping", "paused"}:
                raise s.SessionBusyError(
                    s.text_for(
                        s.get_web_language(),
                        zh=f"会话 {session_id} 仍在运行或停止中，暂时不能归档 Agent。",
                        en=f"Session {session_id} is still running or stopping; the Agent cannot be archived yet.",
                    )
                )
        restore_token = s._agent_session_lifecycle_restore_token(
            payload,
            agent_id=normalized_agent_id,
            session_ids=session_ids,
        )
        for raw in conversations:
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("conversation_id") or "").strip()
            if session_id not in selected:
                continue
            session_kind = s._normalize_session_kind(raw.get("session_kind") or raw.get("sessionKind"))
            child_count += int(session_kind == "child")
            direct_count += int(session_id == normalized_direct_session_id)
            archive_state = {
                "status": "archived",
                "source": "agent_archive",
                "agentId": normalized_agent_id,
                "archivedAt": timestamp,
            }
            raw["archive_state"] = archive_state
            raw["archiveState"] = archive_state
            raw["read_only"] = True
            raw["readOnly"] = True
            raw["hidden_from_index"] = True
            raw["hiddenFromIndex"] = True
            raw["conversation_index_kind"] = s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
            raw["conversationIndexKind"] = s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
            raw["conversation_index_visibility"] = s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
            raw["conversationIndexVisibility"] = s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
            raw["updated_at"] = timestamp
        active_id = str(payload.get("active_conversation_id") or "").strip()
        if active_id in selected:
            replacement_id = s._replacement_session_after_agent_session_removal(
                payload,
                removed_session_ids=selected,
                timestamp=timestamp,
                preserve_removed=True,
            )
            payload["active_conversation_id"] = replacement_id
            if restore_token is not None and replacement_id not in {
                str(raw.get("conversation_id") or "").strip()
                for raw in conversations
                if isinstance(raw, dict)
            }:
                restore_token["createdReplacementSessionId"] = replacement_id
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = timestamp
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    result = {
        "status": "archived",
        "agentId": normalized_agent_id,
        "archivedCount": len(session_ids),
        "directSessionCount": direct_count,
        "childSessionCount": child_count,
        "sessionIds": session_ids,
        "readOnly": True,
        "historyRetention": "sealed",
    }
    if include_restore_token and restore_token is not None:
        result["restoreToken"] = restore_token
    s._record_agent_session_lifecycle_event(
        "agent_archive",
        "conversation.agent_sessions.archived",
        fields={
            "agentId": normalized_agent_id,
            "archivedSessionCount": len(session_ids),
            "directSessionCount": direct_count,
            "childSessionCount": child_count,
            "sessionIds": session_ids[:20],
        },
    )
    return result


def restore_agent_sessions_archive(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    token = restore_token if isinstance(restore_token, dict) else {}
    changed = s._restore_agent_session_lifecycle_state(token)
    return {
        "status": "restored" if changed else "unchanged",
        "changed": changed,
        "agentId": str(token.get("agentId") or "").strip(),
        "sessionIds": list(token.get("sessionIds") or []),
    }


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
    s = _service()
    lang = s.get_web_language()
    parent_id = str(parent_session_id or "").strip()
    request_text = str(user_request or "").strip()
    if not parent_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到父会话。", en="Parent session not found."))
    if not request_text:
        raise s.SessionValidationError(s.text_for(lang, zh="请输入子对话要处理的事项。", en="Enter the child session task."))
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        s._materialize_agent_directory_conversation_locked(payload, parent_id, source="s.create_child_session")
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        source_parent = s._find_conversation_entry(payload, parent_id)
        if source_parent is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到父会话。", en="Parent session not found."))
        s._ensure_session_mutable(parent_id, conversation=source_parent)
        s._ensure_conversation_workspace_metadata(source_parent)
        s._ensure_conversation_agent_metadata(source_parent)
        normalized_parent = s._normalize_conversation(source_parent, ensure_workspace=False)
        root_id = str((normalized_parent or {}).get("rootSessionId") or parent_id).strip() or parent_id
        if str((normalized_parent or {}).get("sessionKind") or "main") == "child":
            root_id = str((normalized_parent or {}).get("rootSessionId") or (normalized_parent or {}).get("parentSessionId") or parent_id).strip() or parent_id
        parent = s._find_conversation_entry(payload, root_id) or source_parent
        s._ensure_conversation_workspace_metadata(parent)
        s._ensure_conversation_agent_metadata(parent)
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = s._now_timestamp()
        child_id = s._new_conversation_id(existing_ids)
        title = s.trim_lines(task_title or request_text, max_lines=1).strip() or s.text_for(lang, zh="子对话", en="Child session")
        agent_id = str(parent.get("agent_id") or parent.get("agentId") or "").strip()
        handoff_context = {
            "source": str(source or "agent_auto_split").strip() or "agent_auto_split",
            "parentSessionId": root_id,
            "sourceSessionId": parent_id,
            "parentMessageId": s._latest_user_message_id(parent_id, s._session_ledger_visible_messages(parent_id)),
            "triggeringUserMessage": request_text,
            "splitReason": split_reason or "Agent judged this request as a separate task.",
            "inheritedFacts": list(inherited_facts or []),
            "relevantFiles": list(relevant_files or []),
            "relevantLogs": list(relevant_logs or []),
            "constraints": list(constraints or []),
            "excludedContextSummary": excluded_context_summary,
        }
        child = s._make_empty_conversation(
            child_id,
            title=title,
            timestamp=now,
            conversation_index_kind=s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        )
        child.update(
            {
                "agent_id": agent_id,
                "agentId": agent_id,
                "session_kind": "child",
                "parent_session_id": root_id,
                "root_session_id": root_id,
                "task_title": title,
                "child_status": "queued" if auto_start else "idle",
                "handoff_context": s._normalize_child_handoff_context(handoff_context),
            }
        )
        s._ensure_conversation_workspace_metadata(child)
        child_ids = s._normalize_string_list(parent.get("child_session_ids") or parent.get("childSessionIds"))
        if child_id not in child_ids:
            child_ids.append(child_id)
        parent["child_session_ids"] = child_ids
        parent["active_child_session_id"] = child_id
        parent.pop("messages", None)
        parent["updated_at"] = now
        conversations.append(child)
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        if switch_to_child:
            payload["active_conversation_id"] = child_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._append_session_conversation_event(
        root_id,
        f"child-session-{child_id}",
        s.EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": s._child_session_created_card(child_id=child_id, title=title, auto_start=auto_start),
            "metadata": {
                "kind": "child_session_card",
                "childSessionId": child_id,
                "childStatus": "queued" if auto_start else "idle",
                "taskTitle": title,
            },
        },
        source="s.create_child_session",
    )
    s._invalidate_session_list_cache()
    s._record_child_session_event(
        "created",
        parent_session_id=root_id,
        child_session_id=child_id,
        fields={"autoStart": bool(auto_start), "switchToChild": bool(switch_to_child), "taskTitle": title},
    )
    if auto_start:
        s._record_child_session_event("autostarted", parent_session_id=root_id, child_session_id=child_id)
        s.submit_session_message(
            child_id,
            s._child_session_initial_prompt(request_text, handoff_context),
            message_metadata={"childSessionStart": True, "parentSessionId": root_id},
            message_source="child_session_autostart",
            lightweight_response=True,
        )
    return {
        "status": "created",
        "parentSessionId": root_id,
        "childSessionId": child_id,
        "childSession": s.get_session_detail(child_id) or {},
        "parentSession": s.get_session_detail(root_id) or {},
        "switched": bool(switch_to_child),
        "autoStarted": bool(auto_start),
    }


def list_child_sessions(session_id: str) -> list[dict[str, Any]]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return []
    _, conversations = s._load_conversations()
    root_id = s._root_session_id_for_conversations(normalized_session_id, conversations)
    children = [
        s._build_session_summary(item)
        for item in conversations
        if str(item.get("parentSessionId") or "").strip() == root_id
        and str(item.get("sessionKind") or "").strip() == "child"
    ]
    children.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return children


def create_supervised_agent_session(
    *,
    agent_id: str,
    title: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a hidden supervised-evolution session bound to an existing Agent."""
    s = _service()

    lang = s.get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="监督会话缺少 Agent 绑定。", en="Supervised session is missing an Agent binding.")
        )
    agent = s.get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise s.SessionValidationError(s._session_agent_unavailable_message("missing_agent", lang=lang))
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = s._now_timestamp()
        session_id = s._new_conversation_id(existing_ids)
        display_title = (
            s.trim_lines(title or "", max_lines=1).strip()
            or s.text_for(lang, zh="监督进化隐藏会话", en="Hidden supervised evolution session")
        )
        conversation = s._make_empty_conversation(
            session_id,
            title=display_title,
            timestamp=now,
            conversation_index_kind=s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
        )
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
        s._ensure_conversation_workspace_metadata(conversation)
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = now
        payload["conversations"] = conversations
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    return s.get_session_detail(session_id) or {}


def delete_chat_session(session_id: str) -> dict:
    """Delete one chat session and return the next active session detail."""
    s = _service()

    delete_result = s._delete_chat_session_state(session_id)
    next_active_id = str(delete_result.get("nextActiveSessionId") or "").strip()
    target = s._load_conversation_detail_target(next_active_id, repair=False, agent_by_id={})
    return s._build_lightweight_session_detail(target) if target is not None else {}


def delete_chat_session_lightweight(session_id: str, *, activate_replacement: bool = False) -> dict[str, Any]:
    """Delete one chat session and return a lightweight UI handoff payload."""
    s = _service()

    deleted_session_id = str(session_id or "").strip()
    delete_result = s._delete_chat_session_state(deleted_session_id, activate_replacement=activate_replacement)
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
    s = _service()

    lang = s.get_web_language()
    old_session_id = str(session_id or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    if not old_session_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    if not normalized_agent_id:
        raise s.SessionValidationError(s.text_for(lang, zh="缺少 Agent ID。", en="Agent id is required."))

    replacement_session_id = ""
    created_at = s._now_timestamp()
    normalized_title = s.trim_lines(title or "", max_lines=1).strip() or s.text_for(lang, zh="新会话", en="New session")
    try:
        with s._CHAT_STATE_LOCK:
            payload = s.load_chat_state(s.PROJECT_ROOT)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            s._materialize_agent_directory_conversation_locked(payload, old_session_id, source="agent_reset_direct_session")
            payload = s._repair_stale_running_conversations(payload)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            old_conversation = s._find_conversation_entry(payload, old_session_id)
            if old_conversation is None:
                raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
            normalized_old = s._normalize_conversation(old_conversation) or {}
            old_phase = s._conversation_phase(old_session_id, normalized_old)
            s._record_session_delete_event(
                "agent_reset_replacement_requested",
                session_id=old_session_id,
                outcome="requested",
                fields={"agentId": normalized_agent_id, "phase": old_phase},
            )
            if old_phase in {"running", "stopping"}:
                raise s.SessionBusyError(
                    s.text_for(
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
            replacement_session_id = s._new_conversation_id(existing_ids | {old_session_id})
            replacement_conversation = s._make_empty_conversation(
                replacement_session_id,
                title=normalized_title,
                timestamp=created_at,
            )
            s._ensure_conversation_workspace_metadata(replacement_conversation)
            replacement_conversation["agent_id"] = normalized_agent_id
            replacement_conversation["agentId"] = normalized_agent_id
            conversations.append(replacement_conversation)
            payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
            payload["active_conversation_id"] = replacement_session_id
            payload["updated_at"] = created_at
            payload["conversations"] = conversations
            s.save_chat_state(s.PROJECT_ROOT, payload)
        s._invalidate_session_list_cache()

        s.agent_directory_service.update_agent_instance(
            normalized_agent_id,
            direct_session_id=replacement_session_id,
            metadata={"previousDirectSessionId": old_session_id},
        )
        delete_result = s._delete_chat_session_state(old_session_id, activate_replacement=True)
        s._record_session_delete_event(
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
            s._remove_replacement_direct_session_after_failed_agent_reset(
                replacement_session_id,
                agent_id=normalized_agent_id,
                fallback_active_session_id=old_session_id,
            )
        try:
            s.agent_directory_service.update_agent_instance(
                normalized_agent_id,
                direct_session_id=old_session_id,
                metadata={"previousDirectSessionId": replacement_session_id},
            )
        except Exception:
            pass
        s._record_session_delete_event(
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


def mark_direct_session_agent_deleted(
    session_id: str,
    *,
    agent_id: str,
    agent_display_name: str = "",
    previous_status: str = "",
    hide_from_index: bool = False,
    include_restore_token: bool = False,
) -> dict[str, Any]:
    """Keep direct-session history while preventing Agent repair from recreating a purged Agent."""
    s = _service()

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
    now = s._now_timestamp()
    try:
        with s._CHAT_STATE_LOCK:
            payload = s.load_chat_state(s.PROJECT_ROOT)
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
                if str(raw.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip() != normalized_session_id:
                    continue
                found = True
                if restore_token is not None:
                    restore_token["previousConversation"] = s.copy.deepcopy(raw)
                changed = s._mark_conversation_agent_deleted(
                    raw,
                    session_id=normalized_session_id,
                    agent_id=normalized_agent_id,
                    agent_display_name=agent_display_name,
                    previous_status=previous_status,
                    hide_from_index=hide_from_index,
                    timestamp=now,
                ) or changed
                break
            if not found:
                conversation = s._make_empty_conversation(
                    normalized_session_id,
                    title=agent_display_name or normalized_session_id,
                    timestamp=now,
                )
                s._ensure_conversation_workspace_metadata(conversation)
                s._mark_conversation_agent_deleted(
                    conversation,
                    session_id=normalized_session_id,
                    agent_id=normalized_agent_id,
                    agent_display_name=agent_display_name,
                    previous_status=previous_status,
                    hide_from_index=hide_from_index,
                    timestamp=now,
                )
                conversations.append(conversation)
                changed = True
            if changed:
                payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
                payload["updated_at"] = now
                s.save_chat_state(s.PROJECT_ROOT, payload)
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
        s._record_direct_session_agent_deleted_event(result, previous_status=previous_status, created_tombstone=False, level="error")
        return result
    if changed:
        s._invalidate_session_list_cache()
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
    s._record_direct_session_agent_deleted_event(result, previous_status=previous_status, created_tombstone=not found)
    return result


def restore_direct_session_agent_deleted_tombstone(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    """Restore a direct-session conversation after a failed pre-purge tombstone."""
    s = _service()

    token = restore_token if isinstance(restore_token, dict) else {}
    normalized_session_id = str(token.get("sessionId") or "").strip()
    normalized_agent_id = str(token.get("agentId") or "").strip()
    if not normalized_session_id:
        return {"changed": False, "sessionId": "", "agentId": normalized_agent_id, "reason": "missing_restore_session"}
    changed = False
    try:
        with s._CHAT_STATE_LOCK:
            payload = s.load_chat_state(s.PROJECT_ROOT)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
                payload["conversations"] = conversations
            current_index = -1
            for index, raw in enumerate(conversations):
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip() == normalized_session_id:
                    current_index = index
                    break
            previous_conversation = token.get("previousConversation")
            if isinstance(previous_conversation, dict):
                restored = s.copy.deepcopy(previous_conversation)
                if current_index >= 0:
                    if conversations[current_index] != restored:
                        conversations[current_index] = restored
                        changed = True
                else:
                    conversations.append(restored)
                    changed = True
            elif current_index >= 0 and s._conversation_agent_deleted_tombstone_matches(
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
                    payload["updated_at"] = s._now_timestamp()
                previous_version = token.get("previousVersion")
                if isinstance(previous_version, int):
                    payload["version"] = previous_version
                else:
                    payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
                s.save_chat_state(s.PROJECT_ROOT, payload)
    except Exception as exc:
        result = {
            "changed": False,
            "sessionId": normalized_session_id,
            "agentId": normalized_agent_id,
            "reason": "restore_failed",
            "errorType": type(exc).__name__,
        }
        s._record_direct_session_agent_deleted_rollback_event(result, level="error")
        return result
    if changed:
        s._invalidate_session_list_cache()
    result = {
        "changed": changed,
        "sessionId": normalized_session_id,
        "agentId": normalized_agent_id,
        "reason": "restored",
    }
    s._record_direct_session_agent_deleted_rollback_event(result)
    return result


def wake_agent_for_inbox_message(message: dict[str, Any]) -> dict[str, Any]:
    """Start the target Agent's direct session so it can answer an inbox message."""
    s = _service()

    message_id = str(message.get("messageId") or message.get("eventId") or "").strip()
    target_agent_id = str(message.get("targetAgentId") or "").strip()
    target_agent = s.get_agent(target_agent_id, include_archived=False) if target_agent_id else None
    archived_target_agent = None if target_agent else (s.get_agent(target_agent_id, include_archived=True) if target_agent_id else None)
    persisted_target_session_id = str(message.get("targetSessionId") or "").strip()
    current_target_session_id = str((target_agent or {}).get("directSessionId") or "").strip()
    target_session_id = (
        current_target_session_id
        if target_agent
        else persisted_target_session_id or str((archived_target_agent or {}).get("directSessionId") or "").strip()
    )
    delivery = {
        "wakeRequested": True,
        "wakeStatus": "skipped",
        "messageId": message_id,
        "targetAgentId": target_agent_id,
        "targetSessionId": target_session_id,
        "persistedTargetSessionId": persisted_target_session_id,
        "targetSessionRedirected": bool(
            target_agent
            and persisted_target_session_id
            and persisted_target_session_id != target_session_id
        ),
        "turnId": "",
        "reason": "",
    }
    if not target_agent:
        archived_status = str((archived_target_agent or {}).get("status") or "").strip().lower()
        if archived_status == "archived":
            delivery["wakeStatus"] = "skipped_archived_agent"
            delivery["reason"] = "target_agent_archived"
            s._record_agent_inbox_wake_event("agent_inbox.wake_skipped_archived_agent", message, delivery, level="warning")
        else:
            delivery["wakeStatus"] = "skipped_missing_agent"
            delivery["reason"] = "target_agent_not_found"
            s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
        return delivery
    target_metadata = target_agent.get("metadata") if isinstance(target_agent.get("metadata"), dict) else {}
    delegation_decision = s.evaluate_delegation_wake_policy(target_metadata.get("delegationPolicy"), agent_id=target_agent_id)
    if not delegation_decision.allowed:
        delivery["wakeStatus"] = "skipped_policy_blocked"
        delivery["reason"] = delegation_decision.reason
        s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
        return delivery
    if not target_session_id:
        delivery["wakeStatus"] = "skipped_no_direct_session"
        delivery["reason"] = "target_agent_has_no_direct_session"
        s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
        return delivery
    if s._is_session_running(target_session_id):
        delivery["wakeStatus"] = "skipped_busy"
        delivery["reason"] = "target_session_busy"
        s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
        return delivery

    with s._AGENT_INBOX_WAKE_STATE_LOCK:
        if message_id in s._AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS:
            delivery["wakeStatus"] = "skipped_in_flight"
            delivery["reason"] = "inbox_message_wake_in_flight"
            s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
            return delivery
        s._AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS.add(message_id)

    try:
        message_metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        research_org_metadata = {
            "researchOrgMessageId": str(message_metadata.get("researchOrgMessageId") or "").strip(),
            "researchOrgDeliveryMode": str(message_metadata.get("researchOrgDeliveryMode") or "").strip(),
            "researchOrgMessageType": str(message_metadata.get("researchOrgMessageType") or "").strip(),
            "researchOrgIntent": str(message_metadata.get("researchOrgIntent") or "").strip(),
            "communicationEdgeId": str(message_metadata.get("communicationEdgeId") or "").strip(),
        }
        prompt = s._format_agent_inbox_wake_prompt(message)
        try:
            detail = s.submit_session_message(
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
        except s.SessionBusyError:
            delivery["wakeStatus"] = "skipped_busy"
            delivery["reason"] = "target_session_busy"
            s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="info")
            return delivery
        except (s.SessionNotFoundError, s.SessionValidationError) as exc:
            delivery["wakeStatus"] = "skipped_invalid_session"
            delivery["reason"] = type(exc).__name__
            s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
            return delivery

        turn_id = str(detail.get("startedTurnId") or "").strip()
        try:
            s.consume_agent_inbox_message(
                target_agent_id,
                message_id,
                consumed_by_session_id=target_session_id,
                consumed_by_turn_id=turn_id,
            )
        except Exception as exc:
            delivery["wakeStatus"] = "started_consume_failed"
            delivery["reason"] = type(exc).__name__
            delivery["turnId"] = turn_id
            s._record_agent_inbox_wake_event("agent_inbox.wake_started_consume_failed", message, delivery, level="warning")
            return delivery

        delivery["wakeStatus"] = "started"
        delivery["turnId"] = turn_id
        s._record_agent_inbox_wake_event("agent_inbox.wake_started", message, delivery, level="info")
        return delivery
    finally:
        with s._AGENT_INBOX_WAKE_STATE_LOCK:
            s._AGENT_INBOX_WAKE_IN_FLIGHT_MESSAGE_IDS.discard(message_id)


def recover_wakeable_agent_inbox_messages_on_startup() -> dict[str, Any]:
    """Attempt the oldest persistent wake-eligible inbox message for each active Agent."""
    s = _service()

    started_at = s._perf_counter()
    summary: dict[str, Any] = {
        "trigger": "backend_startup",
        "scannedAgentCount": 0,
        "eligibleAgentCount": 0,
        "startedCount": 0,
        "skippedCount": 0,
        "errorCount": 0,
        "wakeStatusCounts": {},
        "errorTypeCounts": {},
    }
    try:
        # A restarted process owns no in-memory turns, so repair stale persisted
        # turn markers before submitting recovered inbox work to the scheduler.
        s._load_conversations()
        agents = s.agent_directory_service.list_agents(include_archived=False, detail="summary")
        summary["scannedAgentCount"] = len(agents)
        for agent in agents:
            agent_id = str(agent.get("agentId") or "").strip()
            if not agent_id:
                continue
            try:
                message = s.next_wakeable_agent_inbox_message_for_agent(agent_id)
                if not message:
                    continue
                summary["eligibleAgentCount"] += 1
                delivery = s.wake_agent_for_inbox_message(message)
                wake_status = str(delivery.get("wakeStatus") or "unknown").strip() or "unknown"
                status_counts = summary["wakeStatusCounts"]
                status_counts[wake_status] = int(status_counts.get(wake_status) or 0) + 1
                if wake_status == "started":
                    summary["startedCount"] += 1
                else:
                    summary["skippedCount"] += 1
            except Exception as exc:
                summary["errorCount"] += 1
                error_type = type(exc).__name__
                error_counts = summary["errorTypeCounts"]
                if len(error_counts) < 8 or error_type in error_counts:
                    error_counts[error_type] = int(error_counts.get(error_type) or 0) + 1
    except Exception as exc:
        summary["errorCount"] += 1
        summary["errorTypeCounts"][type(exc).__name__] = 1
    summary["durationMs"] = s._elapsed_ms(started_at)
    s._record_agent_inbox_startup_recovery_event(summary)
    return summary


def append_cli_agent_lifecycle_event(
    session_id: str,
    *,
    event: str = "closed",
    terminal_session: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append a folded CLI Agent lifecycle event to the persisted conversation."""
    s = _service()

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
    lang = s.get_web_language()
    timestamp = s._now_timestamp()
    if normalized_event in {"linked", "session_linked"}:
        content = s.text_for(
            lang,
            zh=f"{label} 已连接 CLI 会话。",
            en=f"{label} linked to a CLI session.",
        )
    elif normalized_event == "resumed":
        content = s.text_for(
            lang,
            zh=f"{label} 已恢复 CLI 会话。",
            en=f"{label} resumed the CLI session.",
        )
    else:
        content = s.text_for(
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
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return None
        existing = s._find_cli_agent_lifecycle_message(
            normalized_session_id,
            s._session_ledger_visible_messages(normalized_session_id),
            lifecycle_key=lifecycle_key,
        )
        if existing is not None:
            return existing
        event_entry = s._make_chat_message("assistant", content, metadata=metadata)
        conversation.pop("messages", None)
        conversation["updated_at"] = event_entry["timestamp"]
        payload["updated_at"] = event_entry["timestamp"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._append_session_conversation_event(
        normalized_session_id,
        str(terminal.get("sourceTurnId") or terminal.get("turnId") or f"cli-lifecycle:{lifecycle_subject}"),
        s.EVENT_CLI_SESSION_LIFECYCLE,
        status=normalized_event,
        payload={"lifecycle": metadata},
        source="cli_agent_lifecycle",
        visible_in_model=normalized_event in {"closed", "failed", "timeout"},
        projection_kind="cli_agent_lifecycle",
        correlation_id=lifecycle_key,
        source_kind="cli_agent",
    )
    s._record_session_cycle_message(
        normalized_session_id,
        event_entry,
        event="cli_agent_lifecycle",
        status=normalized_event,
    )
    s._record_cli_agent_lifecycle_event(
        normalized_session_id,
        event=normalized_event,
        metadata=metadata,
    )
    s._publish_session_detail_snapshot(normalized_session_id)
    normalized = s._normalize_messages(normalized_session_id, [event_entry])
    return normalized[0] if normalized else event_entry


def append_cli_agent_task_result_event(
    session_id: str,
    *,
    task_result: dict[str, Any],
    wake_agent: bool = False,
    wake_reason: str = "",
) -> dict[str, Any] | None:
    """Persist a CLI Agent task result and optionally wake the owning Agent."""
    s = _service()

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
    content = s._format_cli_agent_task_result_content(task_result)
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
        "completedAt": str(task_result.get("completedAt") or s._now_timestamp()).strip(),
        "timedOut": bool(task_result.get("timedOut")),
        "folded": True,
    }
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            return None
        existing = s._find_cli_agent_task_result_message(
            s._session_ledger_visible_messages(normalized_session_id),
            result_key=result_key,
        )
        if existing is not None:
            return existing
        else:
            result_entry = s._make_chat_message("assistant", content, metadata=metadata)
            conversation.pop("messages", None)
            conversation["updated_at"] = result_entry["timestamp"]
            payload["updated_at"] = result_entry["timestamp"]
            s.save_chat_state(s.PROJECT_ROOT, payload)
    journal_turn_id = str(
        task_result.get("sourceTurnId")
        or task_result.get("turnId")
        or s._current_session_turn_id(normalized_session_id)
        or f"cli-task:{result_subject}"
    ).strip()
    journal_tool_call = {
        "name": "cli_agent_run_tool",
        **task_result,
        "status": status,
        "result": content,
        "resultPreview": s.trim_lines(content, max_lines=8),
    }
    s._append_session_conversation_event(
        normalized_session_id,
        journal_turn_id,
        s.EVENT_CLI_TASK_RESULT,
        status=status,
        payload={"toolCall": journal_tool_call},
        source="cli_agent_task_kernel",
        visible_in_model=True,
        projection_kind="cli_agent_task_result",
        tool_call_id=task_id,
        correlation_id=result_key,
        source_kind="cli_agent",
    )
    s._record_session_cycle_message(
        normalized_session_id,
        result_entry,
        event="cli_agent_task_result",
        status=status,
    )
    signal = s._record_chat_next_state_signal(
        session_id=normalized_session_id,
        turn_id=s._current_session_turn_id(normalized_session_id),
        source="runtime",
        kind="cli_agent_result",
        polarity="negative" if status in {"failed", "timeout", "error"} else "neutral",
        mode="directive",
        related_event_code="conversation.cli_agent.task_result",
        summary=s.trim_lines(content, max_lines=8),
        metadata={
            "taskId": task_id,
            "terminalSessionId": terminal_session_id,
            "status": status,
            "wakeReason": str(wake_reason or "").strip(),
        },
    )
    wake_status = ""
    if wake_agent:
        wake_status = s._wake_agent_for_cli_agent_task_result(
            normalized_session_id,
            task_result=task_result,
            result_content=content,
            signal_id=str((signal or {}).get("signalId") or ""),
            wake_reason=wake_reason,
        )
    s._record_cli_agent_task_result_event(
        normalized_session_id,
        task_result=task_result,
        wake_status=wake_status,
        signal_id=str((signal or {}).get("signalId") or ""),
    )
    s._publish_session_detail_snapshot(normalized_session_id)
    if isinstance(result_entry, dict):
        result_entry = dict(result_entry)
        if wake_status:
            result_entry["_cliAgentWakeStatus"] = wake_status
    return result_entry


def _delete_chat_session_state(session_id: str, *, activate_replacement: bool = False) -> dict[str, str]:
    """Delete one chat session and return ids needed by UI and Agent rebind callers."""
    s = _service()

    started_at = s._perf_counter()
    timings: dict[str, int] = {}

    def timed(stage: str, callback: Callable[[], Any]) -> Any:
        stage_started_at = s._perf_counter()
        try:
            return callback()
        finally:
            timings[stage] = s._elapsed_ms(stage_started_at)

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    next_active_id = ""
    with s._CHAT_STATE_LOCK:
        payload = timed("load_state", lambda: s.load_chat_state(s.PROJECT_ROOT))
        timed(
            "materialize_session",
            lambda: s._materialize_agent_directory_conversation_locked(payload, conversation_id, source="s.delete_chat_session"),
        )
        payload = timed("repair_state", lambda: s._repair_stale_running_conversations(payload))
        resolve_started_at = s._perf_counter()
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
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_session_mutable(
            conversation_id,
            conversation=target_conversation,
        )
        s._ensure_conversation_workspace_metadata(target_conversation)
        s._ensure_conversation_agent_metadata(target_conversation)
        target_agent_id = str(target_conversation.get("agent_id") or target_conversation.get("agentId") or "").strip()
        target_agent = s.get_agent(target_agent_id, include_archived=False) if target_agent_id else None
        target_agent_direct_session_id = str((target_agent or {}).get("directSessionId") or "").strip()

        normalized_target = s._normalize_conversation(target_conversation) or {}
        target_phase = s._conversation_phase(conversation_id, normalized_target)
        target_message_count = len(s._session_ledger_visible_messages(conversation_id))
        timings["resolve_target"] = s._elapsed_ms(resolve_started_at)
        s._record_session_delete_event(
            "requested",
            session_id=conversation_id,
            outcome="requested",
            fields={
                "phase": target_phase,
                "agentId": target_agent_id,
                "messageCount": target_message_count,
            },
        )
        if target_phase in {"running", "stopping"}:
            s._record_session_delete_event(
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
            raise s.SessionBusyError(
                s.text_for(
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
            for item in (s._normalize_conversation(raw) for raw in remaining)
            if item is not None
        ]
        replacement_direct_session_id = ""
        agent_unbound = False
        if target_agent and target_agent_direct_session_id == conversation_id:
            timed(
                "unbind_agent",
                lambda: s.update_agent_instance(
                    target_agent_id,
                    direct_session_id="",
                ),
            )
            agent_unbound = True
        else:
            timings["unbind_agent"] = 0

        current_active_id = str(payload.get("active_conversation_id") or "").strip()
        if any(item["id"] == current_active_id for item in normalized_remaining) and current_active_id != conversation_id:
            next_active_id = current_active_id
        elif normalized_remaining:
            latest = max(
                normalized_remaining,
                key=lambda item: s._timestamp_sort_key(item.get("updatedAt") or ""),
            )
            next_active_id = latest["id"]
        else:
            now = s._now_timestamp()
            next_active_id = s._new_conversation_id({conversation_id})
            replacement_conversation = s._make_empty_conversation(
                next_active_id,
                title=s.text_for(lang, zh="新会话", en="New session"),
                timestamp=now,
            )
            remaining = [
                replacement_conversation
            ]

        now = s._now_timestamp()
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["active_conversation_id"] = next_active_id
        payload["updated_at"] = now
        payload["conversations"] = remaining
        try:
            timed("save_state", lambda: s.save_chat_state(s.PROJECT_ROOT, payload))
        except Exception as exc:
            if agent_unbound:
                try:
                    timed(
                        "rollback_agent_unbind",
                        lambda: s.update_agent_instance(
                            target_agent_id,
                            direct_session_id=conversation_id,
                        ),
                    )
                    s._record_session_delete_event(
                        "agent_unbind_rolled_back",
                        session_id=conversation_id,
                        outcome="rolled_back",
                        level="warning",
                        fields={
                            "agentId": target_agent_id,
                            "reason": type(exc).__name__,
                        },
                    )
                except Exception as rollback_exc:
                    s._record_session_delete_event(
                        "agent_unbind_rollback_failed",
                        session_id=conversation_id,
                        outcome="rollback_failed",
                        level="error",
                        fields={
                            "agentId": target_agent_id,
                            "reason": type(exc).__name__,
                            "rollbackError": type(rollback_exc).__name__,
                        },
                    )
            raise

    s._invalidate_session_list_cache()
    if target_agent and target_agent_direct_session_id == conversation_id:
        s._record_session_delete_event(
            "agent_unbound",
            session_id=conversation_id,
            outcome="unbound",
            fields={
                "agentId": target_agent_id,
                "previousDirectSessionId": conversation_id,
            },
        )
    cleanup_started_at = s._perf_counter()
    s._set_session_running(conversation_id, False)
    s._clear_session_turn_control(conversation_id)
    s._clear_session_live_output(conversation_id)
    removed_runtime_cache_entries = s._invalidate_session_agent_runtime_cache(conversation_id)
    timings["runtime_cleanup"] = s._elapsed_ms(cleanup_started_at)
    s._record_session_delete_event(
        "deleted",
        session_id=conversation_id,
        outcome="deleted",
        fields={
            "nextActiveSessionId": next_active_id,
            "agentId": target_agent_id,
            "replacementDirectSessionId": replacement_direct_session_id,
            "remainingCount": len(remaining),
            "removedAgentRuntimeCacheEntries": removed_runtime_cache_entries,
            "durationMs": s._elapsed_ms(started_at),
            "timingsMs": timings,
        },
    )
    return {
        "nextActiveSessionId": next_active_id,
        "replacementDirectSessionId": replacement_direct_session_id,
    }


def _agent_session_conversation_ids(
    conversations: list[Any],
    *,
    agent_id: str,
    direct_session_id: str = "",
) -> list[str]:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_direct_session_id = str(direct_session_id or "").strip()
    selected: set[str] = {normalized_direct_session_id} if normalized_direct_session_id else set()
    ordered_ids: list[str] = []
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("conversation_id") or "").strip()
        raw_agent_id = str(raw.get("agent_id") or raw.get("agentId") or "").strip()
        if session_id and normalized_agent_id and raw_agent_id == normalized_agent_id:
            selected.add(session_id)
    changed = True
    while changed:
        changed = False
        for raw in conversations:
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("conversation_id") or "").strip()
            if not session_id or session_id in selected:
                continue
            parent_id = str(raw.get("parent_session_id") or raw.get("parentSessionId") or "").strip()
            root_id = str(raw.get("root_session_id") or raw.get("rootSessionId") or "").strip()
            if parent_id in selected or root_id in selected:
                selected.add(session_id)
                changed = True
    for raw in conversations:
        if not isinstance(raw, dict):
            continue
        session_id = str(raw.get("conversation_id") or "").strip()
        if session_id and session_id in selected and session_id not in ordered_ids:
            ordered_ids.append(session_id)
    return ordered_ids


def _agent_session_lifecycle_restore_token(
    payload: dict[str, Any],
    *,
    agent_id: str,
    session_ids: list[str],
) -> dict[str, Any]:
    s = _service()
    selected = set(session_ids)
    previous_conversations = [
        {
            "index": index,
            "conversation": s.copy.deepcopy(raw),
        }
        for index, raw in enumerate(list(payload.get("conversations") or []))
        if isinstance(raw, dict)
        and str(raw.get("conversation_id") or "").strip() in selected
    ]
    return {
        "agentId": str(agent_id or "").strip(),
        "sessionIds": list(session_ids),
        "previousConversations": previous_conversations,
        "previousActiveConversationId": str(payload.get("active_conversation_id") or "").strip(),
        "previousUpdatedAt": str(payload.get("updated_at") or "").strip(),
        "previousVersion": payload.get("version"),
        "createdReplacementSessionId": "",
        "workspaceMoves": [],
    }


def _agent_session_purge_cleanup_marker_path(staging_root: Path) -> Path:
    s = _service()
    return staging_root.parent / (
        staging_root.name + s._AGENT_SESSION_PURGE_CLEANUP_MARKER_SUFFIX
    )


def _agent_session_purge_manifest_path(staging_root: Path) -> Path:
    s = _service()
    return staging_root / s._AGENT_SESSION_PURGE_MANIFEST


def _agent_session_purge_staging_root(
    sessions_root: Path,
    *,
    agent_id: str,
    nonce: str,
) -> Path:
    s = _service()
    token = s._safe_session_workspace_token(agent_id)
    staging_root = (sessions_root / f".agent-purge-{token}-{nonce}").resolve()
    if not staging_root.is_relative_to(sessions_root):
        raise s.SessionValidationError(f"Invalid Agent session purge staging path: {staging_root}")
    return staging_root


def _agent_session_purge_staging_root_is_safe(
    staging_root: Path,
    *,
    allowed_roots: list[Path],
) -> bool:
    s = _service()
    return bool(
        staging_root.name.startswith(".agent-purge-")
        and any(staging_root.parent == root for root in allowed_roots)
        and not staging_root.is_symlink()
        and not s._path_is_reparse_point(staging_root)
    )


def _agent_session_workspace_roots() -> list[Path]:
    s = _service()
    roots: list[Path] = []
    for candidate in (
        s.developer_sandbox.sandboxed_workspace_path(s.PROJECT_ROOT, "sessions"),
        s.developer_sandbox.formal_workspace_path(s.PROJECT_ROOT, "sessions"),
    ):
        resolved = candidate.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _delete_agent_session_purge_staging_root(staging_root: Path) -> None:
    s = _service()
    if not s._agent_session_purge_staging_root_is_safe(
        staging_root,
        allowed_roots=s._agent_session_workspace_roots(),
    ):
        raise s.SessionValidationError(
            f"Invalid Agent session purge staging path: {staging_root}"
        )
    shutil.rmtree(staging_root)


def _write_agent_session_purge_manifest(
    staging_root: Path,
    manifest: dict[str, Any],
) -> None:
    s = _service()
    if s._path_is_reparse_point(staging_root):
        raise s.SessionValidationError(
            f"Agent session purge staging root is a reparse point: {staging_root}"
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    s._write_agent_session_purge_record(
        s._agent_session_purge_manifest_path(staging_root),
        manifest,
    )


def _write_agent_session_purge_record(
    path: Path,
    payload: dict[str, Any],
) -> None:
    s = _service()
    temporary_path = path.with_name(f"{path.name}.{s.secrets.token_hex(4)}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _read_agent_session_purge_cleanup_marker(
    marker_path: Path,
) -> dict[str, Any] | None:
    s = _service()
    if (
        not marker_path.is_file()
        or marker_path.is_symlink()
        or s._path_is_reparse_point(marker_path)
    ):
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or str(payload.get("state") or "").strip() != "cleanup_pending"
    ):
        return None
    return payload


def _read_agent_session_purge_manifest(
    staging_root: Path,
) -> dict[str, Any] | None:
    s = _service()
    manifest_path = s._agent_session_purge_manifest_path(staging_root)
    if (
        not manifest_path.is_file()
        or manifest_path.is_symlink()
        or s._path_is_reparse_point(manifest_path)
    ):
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _restore_agent_session_lifecycle_state(restore_token: dict[str, Any]) -> bool:
    s = _service()
    token = restore_token if isinstance(restore_token, dict) else {}
    session_ids = {
        str(item or "").strip()
        for item in list(token.get("sessionIds") or [])
        if str(item or "").strip()
    }
    if not session_ids:
        return False
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = [
            raw
            for raw in list(payload.get("conversations") or [])
            if isinstance(raw, dict)
            and str(raw.get("conversation_id") or "").strip() not in session_ids
        ]
        replacement_id = str(token.get("createdReplacementSessionId") or "").strip()
        if replacement_id:
            conversations = [
                raw
                for raw in conversations
                if str(raw.get("conversation_id") or "").strip() != replacement_id
            ]
        previous = list(token.get("previousConversations") or [])
        for item in sorted(
            (item for item in previous if isinstance(item, dict)),
            key=lambda item: int(item.get("index") or 0),
        ):
            raw = item.get("conversation")
            if not isinstance(raw, dict):
                continue
            index = max(0, min(int(item.get("index") or 0), len(conversations)))
            conversations.insert(index, s.copy.deepcopy(raw))
        payload["conversations"] = conversations
        payload["active_conversation_id"] = str(token.get("previousActiveConversationId") or "").strip()
        previous_updated_at = str(token.get("previousUpdatedAt") or "").strip()
        payload["updated_at"] = previous_updated_at or s._now_timestamp()
        previous_version = token.get("previousVersion")
        payload["version"] = previous_version if isinstance(previous_version, int) else int(
            payload.get("version") or s.CHAT_STATE_VERSION
        )
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    return True


def _restore_staged_agent_workspace_move(move: dict[str, Any]) -> bool:
    s = _service()
    source_value = str(move.get("source") or "").strip()
    staged_value = str(move.get("staged") or "").strip()
    if not source_value or not staged_value:
        raise s.SessionValidationError("Agent session purge restore path is missing.")
    source = Path(source_value)
    staged = Path(staged_value)
    source_exists = source.exists()
    staged_exists = staged.exists()
    if source_exists and not staged_exists:
        return False
    if not source_exists and not staged_exists:
        raise FileNotFoundError(
            f"Agent session workspace is missing from source and staging: {source}"
        )
    if source_exists and staged_exists:
        raise FileExistsError(
            f"Agent session workspace restore conflicts with an existing source: {source}"
        )
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(source))
    if not source.exists() or staged.exists():
        raise OSError(f"Agent session workspace restore did not converge: {source}")
    return True


def _replacement_session_after_agent_session_removal(
    payload: dict[str, Any],
    *,
    removed_session_ids: set[str],
    timestamp: str,
    preserve_removed: bool = False,
) -> str:
    s = _service()
    current_active_id = str(payload.get("active_conversation_id") or "").strip()
    remaining = [
        raw
        for raw in list(payload.get("conversations") or [])
        if isinstance(raw, dict)
        and str(raw.get("conversation_id") or "").strip() not in removed_session_ids
    ]
    remaining_ids = {
        str(raw.get("conversation_id") or "").strip()
        for raw in remaining
        if str(raw.get("conversation_id") or "").strip()
    }
    if current_active_id and current_active_id in remaining_ids:
        return current_active_id
    if remaining:
        return str(
            max(
                remaining,
                key=lambda raw: s._timestamp_sort_key(raw.get("updated_at") or raw.get("updatedAt") or ""),
            ).get("conversation_id")
            or ""
        ).strip()
    replacement_id = s._new_conversation_id(removed_session_ids)
    replacement = s._make_empty_conversation(
        replacement_id,
        title=s.text_for(s.get_web_language(), zh="新会话", en="New session"),
        timestamp=timestamp,
    )
    payload["conversations"] = (
        list(payload.get("conversations") or []) + [replacement]
        if preserve_removed
        else [replacement]
    )
    return replacement_id


def _ensure_agent_direct_session_not_reassigned(
    agent_id: str,
    direct_session_id: str,
) -> None:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_direct_session_id = str(direct_session_id or "").strip()
    if not normalized_agent_id or not normalized_direct_session_id:
        return
    for agent in s.agent_directory_service.list_agents(include_archived=False):
        if not isinstance(agent, dict):
            continue
        active_agent_id = str(agent.get("agentId") or "").strip()
        if not active_agent_id or active_agent_id == normalized_agent_id:
            continue
        if (
            str(agent.get("directSessionId") or "").strip()
            == normalized_direct_session_id
        ):
            raise s.SessionValidationError(
                "Agent direct session is now bound to another active Agent "
                f"({active_agent_id}); archive or purge cannot take ownership "
                f"of session {normalized_direct_session_id}."
            )


def _safe_session_workspace_token(session_id: str) -> str:
    s = _service()
    raw = str(session_id or "").strip()
    token = s._SESSION_WORKSPACE_SAFE_CHARS.sub("-", raw).strip("._-")
    if not token:
        token = "session"
    if token != raw or len(token) > 96:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:10]
        token = f"{token[:84].rstrip('._-') or 'session'}-{digest}"
    return token


def _record_agent_session_lifecycle_event(
    phase: str,
    event_code: str,
    *,
    fields: dict[str, Any],
    outcome: str = "succeeded",
    level: str = "info",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            phase,
            event_code,
            outcome=outcome,
            level=level,
            fields=fields,
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
    s = _service()
    outcome = "failed" if str(result.get("reason") or "") == "tombstone_failed" else "persisted"
    try:
        s.record_runtime_scene_event(
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
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _child_session_created_card(*, child_id: str, title: str, auto_start: bool) -> str:
    s = _service()
    status = "已自动开始" if auto_start else "已创建"
    return "\n".join(
        [
            f"子对话：{title}",
            f"状态：{status}",
            f"childSessionId: {child_id}",
        ]
    )


def _child_session_initial_prompt(user_request: str, handoff_context: dict[str, Any]) -> str:
    s = _service()
    context = s._normalize_child_handoff_context(handoff_context) or {}
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


def _record_child_session_event(
    phase: str,
    *,
    parent_session_id: str,
    child_session_id: str,
    fields: dict[str, Any] | None = None,
    outcome: str = "recorded",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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
            child_log_path=f"conversations/{s._safe_session_workspace_token(parent_session_id)}-children.jsonl",
            child_log_payload={
                "parentSessionId": str(parent_session_id or "").strip(),
                "childSessionId": str(child_session_id or "").strip(),
                "phase": str(phase or "").strip(),
                "createdAt": s._now_timestamp(),
                **(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _raw_conversation_child_session_ids(conversation: dict[str, Any]) -> list[str]:
    s = _service()
    return s._normalize_string_list(conversation.get("child_session_ids") or conversation.get("childSessionIds"))


def _wake_agent_for_cli_agent_task_result(
    session_id: str,
    *,
    task_result: dict[str, Any],
    result_content: str,
    signal_id: str = "",
    wake_reason: str = "",
) -> str:
    s = _service()
    if s._is_session_running(session_id):
        return "guided_running"
    lang = s.get_web_language()
    prompt = "\n".join(
        [
            "CLI Agent 已返回任务结果，请把它当作当前会话的工具结果继续处理。",
            "先吸收结果，再决定是否需要继续主 Agent 侧动作；不要因为看到 CLI 结果而重复启动同一个 CLI Agent。",
            result_content,
        ]
    ).strip()
    requested_leases = ["readonly_chat"]
    lease_decision = s._check_chat_turn_lease_decision(requested_leases)
    if not lease_decision.allowed:
        return "wake_blocked_by_lease"
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversation = s._find_conversation_entry(payload, session_id)
        if conversation is None:
            return "wake_session_missing"
        if s._is_session_running(session_id):
            return "guided_running"
        s._ensure_conversation_agent_metadata(conversation)
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = s._resolve_active_agent_for_turn(session_id, agent_id, lang=lang)
        history_messages = s._session_ledger_visible_messages(session_id)
        active_task = s._normalize_session_active_task(conversation.get("active_task") or conversation.get("activeTask"))
        if not s._is_task_tool_backed_active_task(active_task):
            active_task = None
        turn_control = s._create_session_turn_control(session_id)
        conversation["last_turn_status"] = "running"
        conversation["updated_at"] = s._now_timestamp()
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = conversation["updated_at"]
        s.save_chat_state(s.PROJECT_ROOT, payload)
        s._set_session_running(session_id, True, turn_id=turn_control.turn_id, leases=requested_leases)
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_control.turn_id,
            status="running",
            agent_id=agent_id,
            leases=requested_leases,
            user_message=prompt,
            started_at=conversation["updated_at"],
            updated_at=conversation["updated_at"],
        )
    s._set_session_waiting_live_output(session_id, turn_id=turn_control.turn_id)
    s._record_session_turn_started_event(
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
        "agent_snapshot": dict(agent) if isinstance(agent, dict) else {},
        "agent_prompt_snapshot": dict(conversation.get("agentPromptSnapshot") or {})
        if isinstance(conversation.get("agentPromptSnapshot"), dict)
        else {},
        "leases": requested_leases,
        "llm_slot": Any,
        "submit_timing_fields": {"source": "cli_agent_result", "signalId": signal_id, "wakeReason": str(wake_reason or "").strip()},
        "submit_started_at_monotonic": s._perf_counter(),
    }
    s._record_session_turn_scheduled_event(context)
    try:
        s._schedule_session_turn(context)
    except Exception as exc:
        s._persist_chat_turn_work_run(
            session_id=session_id,
            turn_id=turn_control.turn_id,
            status="failed",
            leases=requested_leases,
            user_message=prompt,
            summary=f"{type(exc).__name__}: {exc}",
        )
        s._set_session_running(session_id, False, turn_id=turn_control.turn_id)
        s._clear_session_turn_control(session_id, turn_id=turn_control.turn_id)
        s._persist_session_turn_failure(session_id, context, exc)
        return "wake_schedule_failed"
    return "wake_scheduled"


def _format_cli_agent_task_result_content(task_result: dict[str, Any]) -> str:
    s = _service()
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
    preview = s.trim_lines(task_result.get("taskPreview") or "", max_lines=2)
    if preview:
        lines.append(f"任务：{preview}")
    segments = list(task_result.get("resultSegments") or [])
    segment_lines: list[str] = []
    for item in segments[-8:]:
        if not isinstance(item, dict):
            continue
        text = s.trim_lines(item.get("text") or "", max_lines=8)
        if not text:
            continue
        kind = str(item.get("kind") or "output").strip() or "output"
        segment_lines.append(f"- [{kind}] {text}")
    if segment_lines:
        lines.append("最近完整片段：")
        lines.extend(segment_lines)
    else:
        stdout = s.trim_lines(task_result.get("stdoutPreview") or "", max_lines=12)
        if stdout:
            lines.append("输出摘要：")
            lines.append(stdout)
    if status in {"failed", "timeout", "error"}:
        lines.append("请基于该失败/超时结果判断下一步策略，不要重复调用同一个 CLI 任务，除非你需要验证新的假设。")
    return "\n".join(line for line in lines if str(line or "").strip()).strip()


def _find_cli_agent_lifecycle_message(
    conversation_id: str,
    messages: list[dict[str, Any]],
    *,
    lifecycle_key: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized_key = str(lifecycle_key or "").strip()
    if not normalized_key:
        return None
    normalized_messages = s._normalize_messages(conversation_id, messages)
    for message in normalized_messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() not in {"cli_agent_lifecycle", s.EVENT_CLI_SESSION_LIFECYCLE}:
            continue
        if str(metadata.get("lifecycleKey") or "").strip() == normalized_key:
            return message
    return None


def _find_cli_agent_task_result_message(
    messages: list[dict[str, Any]],
    *,
    result_key: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized_key = str(result_key or "").strip()
    if not normalized_key:
        return None
    for message in messages:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() not in {"cli_agent_task_result", s.EVENT_CLI_TASK_RESULT}:
            continue
        if str(metadata.get("resultKey") or "").strip() == normalized_key:
            return message
    return None


def _record_cli_agent_lifecycle_event(
    session_id: str,
    *,
    event: str,
    metadata: dict[str, Any],
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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
        s._debug_logger.warning(
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
    s = _service()
    try:
        s.record_runtime_scene_event(
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
        s._debug_logger.warning(
            f"runtime scene cli task result log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _deliver_agent_inbox_turn_reply(reply: dict[str, Any]) -> None:
    s = _service()
    target_agent_id = str(reply.get("targetAgentId") or "").strip()
    source_agent_id = str(reply.get("sourceAgentId") or "").strip()
    if not target_agent_id or not source_agent_id:
        return
    try:
        from core.agent_kernel.adapters import submit_agent_message_event

        metadata = s._agent_inbox_reply_kernel_metadata(
            reply,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        )
        source_id = ":".join(
            item
            for item in (
                "agent-inbox-reply",
                str(reply.get("sourceSessionId") or "").strip(),
                str(metadata.get("sourceMessageId") or "").strip(),
                source_agent_id,
                target_agent_id,
            )
            if item
        )
        kernel_result = submit_agent_message_event(
            source="agent_inbox_reply",
            sender={"type": "agent", "id": source_agent_id, "agentId": source_agent_id},
            recipient_agent_ids=[target_agent_id],
            content=str(reply.get("content") or ""),
            correlation_id=str(reply.get("threadId") or "").strip(),
            wake_target=True,
            metadata=metadata,
            source_id=source_id,
        )
        kernel_delivery = s._agent_inbox_kernel_delivery(kernel_result, target_agent_id)
        message = s._agent_inbox_message_from_kernel_delivery(
            target_agent_id,
            kernel_delivery,
            fallback={
                "sourceAgentId": source_agent_id,
                "targetAgentId": target_agent_id,
                "metadata": metadata,
            },
        )
        delivery = kernel_delivery.get("wake") if isinstance(kernel_delivery.get("wake"), dict) else {}
        if str(kernel_delivery.get("status") or "").strip() != "delivered":
            delivery = {
                "wakeRequested": True,
                "wakeStatus": "failed",
                "targetAgentId": target_agent_id,
                "targetSessionId": str(kernel_delivery.get("targetSessionId") or "").strip(),
                "turnId": "",
                "reason": str(kernel_delivery.get("reason") or "").strip(),
            }
            s._record_agent_inbox_reply_event("agent_inbox.reply_failed", message, delivery, level="warning", outcome="failed")
            return
        s._record_agent_inbox_reply_event("agent_inbox.reply_delivered", message, delivery, outcome="delivered")
    except Exception as exc:
        s._record_agent_inbox_reply_event(
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


def _build_agent_inbox_turn_reply(
    messages: list[dict[str, Any]],
    *,
    assistant_text: str,
    tool_calls: list[dict[str, Any]] | None = None,
    source_session_id: str,
    source_turn_id: str,
) -> dict[str, Any] | None:
    s = _service()
    content = str(assistant_text or "").strip()
    if not content:
        return None
    inbound = s._latest_agent_inbox_user_message(messages)
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
    skip_reason = s._agent_inbox_auto_reply_skip_reason(
        content,
        tool_calls=tool_calls or [],
        source_agent_id=source_agent_id,
    )
    if skip_reason:
        s._record_agent_inbox_reply_skipped(
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
        "summary": s.trim_lines(content, max_lines=4),
        "metadata": {
            "kind": "agent_inbox_reply",
            "replyToMessageId": original_message_id,
            "replyToTurnId": str(metadata.get("turnId") or "").strip(),
            "sourceTurnId": str(source_turn_id or "").strip(),
        },
    }


def _agent_inbox_message_from_kernel_delivery(
    target_agent_id: str,
    delivery: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    message_id = str(
        delivery.get("inboxMessageId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("messageId")
        or ""
    ).strip()
    if message_id:
        for message in s.agent_directory_service.list_agent_inbox_messages_for_agent(
            target_agent_id,
            limit=100,
            status="",
        ):
            if str(message.get("messageId") or message.get("eventId") or "").strip() == message_id:
                return message
    message = dict(fallback)
    if message_id:
        message["messageId"] = message_id
        message.setdefault("eventId", message_id)
    message["targetAgentId"] = str(target_agent_id or "").strip()
    message["targetSessionId"] = str(
        delivery.get("targetSessionId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("targetSessionId")
        or ""
    ).strip()
    return message


def _agent_inbox_kernel_delivery(kernel_result: dict[str, Any], target_agent_id: str) -> dict[str, Any]:
    s = _service()
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    deliveries = outcome.get("deliveries") if isinstance(outcome.get("deliveries"), list) else []
    normalized_target_agent_id = str(target_agent_id or "").strip()
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        if str(delivery.get("targetAgentId") or "").strip() == normalized_target_agent_id:
            return dict(delivery)
    return dict(deliveries[0]) if deliveries and isinstance(deliveries[0], dict) else {}


def _agent_inbox_reply_kernel_metadata(
    reply: dict[str, Any],
    *,
    source_agent_id: str,
    target_agent_id: str,
) -> dict[str, Any]:
    s = _service()
    reply_metadata = reply.get("metadata") if isinstance(reply.get("metadata"), dict) else {}
    reply_to_message_id = str(reply_metadata.get("replyToMessageId") or "").strip()
    source_turn_id = str(reply_metadata.get("sourceTurnId") or "").strip()
    thread_id = str(reply.get("threadId") or "").strip()
    projection_id = thread_id or reply_to_message_id or source_turn_id
    metadata = {
        "sourceSurface": "agent_inbox_reply",
        "sourceSessionId": str(reply.get("sourceSessionId") or "").strip(),
        "sourceMessageId": source_turn_id or reply_to_message_id,
        "projectionRef": {"kind": "agent_inbox_reply", "id": projection_id},
        "senderAgentId": source_agent_id,
        "sourceAgentId": source_agent_id,
        "targetAgentId": target_agent_id,
        "inboxKind": "agent_inbox_reply",
        "messageSummary": str(reply.get("summary") or "").strip(),
        "inboxCreatedBy": "agent_inbox_reply",
        "replyToMessageId": reply_to_message_id,
        "replyToTurnId": str(reply_metadata.get("replyToTurnId") or "").strip(),
        "sourceTurnId": source_turn_id,
    }
    if reply_metadata:
        metadata["agentToolMetadataJson"] = json.dumps(reply_metadata, ensure_ascii=False, sort_keys=True)
    return {key: value for key, value in metadata.items() if value not in ("", None)}


def _agent_inbox_auto_reply_skip_reason(
    assistant_text: str,
    *,
    tool_calls: list[dict[str, Any]],
    source_agent_id: str,
) -> str:
    s = _service()
    if s._agent_message_tool_sent_to_source(tool_calls, source_agent_id=source_agent_id):
        return "explicit_agent_message_sent"
    if s._looks_like_agent_message_delivery_confirmation(assistant_text):
        return "operation_confirmation"
    return ""


def _is_agent_inbox_message_entry(item: Any) -> bool:
    s = _service()
    if not isinstance(item, dict):
        return False
    if str(item.get("role") or "").strip().lower() != "user":
        return False
    if s._message_metadata_kind(item) == "agent_inbox_message":
        return True
    return s._looks_like_agent_inbox_protocol_message(item.get("content"))


def _latest_agent_inbox_user_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = _service()
    for item in reversed(list(messages or [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() == "agent_inbox_message":
            return item
    return None


def _looks_like_agent_inbox_protocol_message(text: Any) -> bool:
    s = _service()
    value = str(text or "").lstrip()
    if not value:
        return False
    return value.startswith("[Agent 私信]") or value.startswith("[Agent 私信回复]")


def _format_agent_inbox_wake_prompt(message: dict[str, Any]) -> str:
    s = _service()
    source_code = str(message.get("sourceAgentCode") or "").strip()
    source_name = str(message.get("sourceAgentName") or "").strip()
    source_agent_id = str(message.get("sourceAgentId") or "").strip()
    source_label = " · ".join(item for item in (source_code, source_name) if item) or source_agent_id or "外部来源"
    inbox_kind = str(message.get("kind") or "").strip()
    content = str(message.get("content") or "").strip()
    summary = s.trim_lines(str(message.get("summary") or ""), max_lines=4)
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


def _record_agent_inbox_reply_event(
    event_code: str,
    message: dict[str, Any],
    delivery: dict[str, Any],
    *,
    level: str = "info",
    outcome: str = "observed",
) -> None:
    s = _service()
    try:
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        s.record_runtime_scene_event(
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
                "kernelEventId": str(metadata.get("kernelEventId") or "").strip(),
                "kernelTaskId": str(metadata.get("kernelTaskId") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_inbox_reply_skipped(
    *,
    reason: str,
    source_agent_id: str,
    target_agent_id: str,
    original_message_id: str,
    source_session_id: str,
    source_turn_id: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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


def _record_agent_inbox_wake_event(
    event_code: str,
    message: dict[str, Any],
    delivery: dict[str, Any],
    *,
    level: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
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
                "persistedTargetSessionId": str(delivery.get("persistedTargetSessionId") or "").strip(),
                "targetSessionRedirected": bool(delivery.get("targetSessionRedirected")),
                "turnId": str(delivery.get("turnId") or "").strip(),
                "wakeStatus": str(delivery.get("wakeStatus") or "").strip(),
                "reason": str(delivery.get("reason") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_inbox_idle_drain_event(
    message: dict[str, Any],
    delivery: dict[str, Any],
) -> None:
    s = _service()
    wake_status = str(delivery.get("wakeStatus") or "").strip() or "observed"
    try:
        s.record_runtime_scene_event(
            "agent_inbox",
            "idle_drain",
            "agent_inbox.idle_drain_started" if wake_status == "started" else "agent_inbox.idle_drain_skipped",
            message="Agent inbox idle drain attempted a queued wake.",
            level="info" if wake_status == "started" else "warning",
            outcome=wake_status,
            fields={
                "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
                "sourceAgentId": str(message.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(message.get("targetAgentId") or "").strip(),
                "targetSessionId": str(delivery.get("targetSessionId") or "").strip(),
                "turnId": str(delivery.get("turnId") or "").strip(),
                "wakeStatus": wake_status,
                "reason": str(delivery.get("reason") or "").strip(),
                "trigger": "session_release",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_inbox_startup_recovery_event(summary: dict[str, Any]) -> None:
    s = _service()
    error_count = max(0, int(summary.get("errorCount") or 0))
    try:
        s.record_runtime_scene_event(
            "agent_inbox",
            "startup_recovery",
            "agent_inbox.startup_recovery_completed",
            message="Persistent wake-eligible Agent inbox messages were scanned after backend startup.",
            level="warning" if error_count else "info",
            outcome="degraded" if error_count else "completed",
            fields=dict(summary),
            lifecycle=True,
        )
    except Exception:
        return
