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
import copy
import re
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
    replacement_snapshot: dict[str, Any] | None = None
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
        replacement_id = str((restore_token or {}).get("createdReplacementSessionId") or "").strip()
        if replacement_id:
            entry = s._find_conversation_entry(payload, replacement_id)
            if isinstance(entry, dict):
                replacement_snapshot = dict(entry)

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
    from . import directory_bridge

    for session_id in session_ids:
        directory_bridge.archive_directory_session_safe(session_id)
    if replacement_snapshot is not None:
        directory_bridge.sync_conversation_record(replacement_snapshot)
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


def reset_all_agent_test_conversations() -> dict[str, Any]:
    """Permanently clear every Agent-owned test conversation without deleting Agents.

    This is an explicit maintenance boundary, not an archive workflow: the caller has
    already declared the conversation domain disposable.  Agent definitions, model
    bindings, team membership, knowledge, and research artifacts are intentionally
    left in place.  The operation refuses active turns, removes every Agent-owned
    root/child conversation, clears direct-session bindings and inbox wake records,
    then destroys only the matching session workspaces.
    """
    s = _service()
    timestamp = s._now_timestamp()
    agents = s.agent_directory_service.list_agents(include_archived=True, detail="full")
    agent_ids = {
        str(agent.get("agentId") or "").strip()
        for agent in agents
        if str(agent.get("agentId") or "").strip()
    }
    direct_session_ids = {
        str(agent.get("directSessionId") or "").strip()
        for agent in agents
        if str(agent.get("directSessionId") or "").strip()
    }
    session_ids: list[str] = []
    payload_before: dict[str, Any] | None = None
    direct_bindings_before: dict[str, str] = {}

    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
        selected = set(direct_session_ids)
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            session_id = str(conversation.get("conversation_id") or "").strip()
            agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
            if session_id and agent_id in agent_ids:
                selected.add(session_id)
        changed = True
        while changed:
            changed = False
            for conversation in conversations:
                if not isinstance(conversation, dict):
                    continue
                session_id = str(conversation.get("conversation_id") or "").strip()
                if not session_id or session_id in selected:
                    continue
                parent_id = str(conversation.get("parent_session_id") or conversation.get("parentSessionId") or "").strip()
                root_id = str(conversation.get("root_session_id") or conversation.get("rootSessionId") or "").strip()
                if parent_id in selected or root_id in selected:
                    selected.add(session_id)
                    changed = True
        session_ids = [
            str(conversation.get("conversation_id") or "").strip()
            for conversation in conversations
            if isinstance(conversation, dict)
            and str(conversation.get("conversation_id") or "").strip() in selected
        ]
        for session_id in session_ids:
            normalized = s._normalize_conversation(
                next(
                    item
                    for item in conversations
                    if isinstance(item, dict)
                    and str(item.get("conversation_id") or "").strip() == session_id
                ),
                ensure_workspace=False,
                lightweight=True,
            ) or {"id": session_id}
            if s._conversation_phase(session_id, normalized) in {"queued", "running", "stopping", "paused"}:
                raise s.SessionBusyError(
                    f"Session {session_id} is still active; finish or stop it before resetting test conversations."
                )
        payload_before = s.copy.deepcopy(payload)
        payload["conversations"] = [
            item
            for item in conversations
            if not isinstance(item, dict)
            or str(item.get("conversation_id") or "").strip() not in selected
        ]
        remaining_ids = [
            str(item.get("conversation_id") or "").strip()
            for item in payload["conversations"]
            if isinstance(item, dict) and str(item.get("conversation_id") or "").strip()
        ]
        payload["active_conversation_id"] = remaining_ids[0] if remaining_ids else ""
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = timestamp
        s.save_chat_state(s.PROJECT_ROOT, payload)

    workspace_moves: list[dict[str, str]] = []
    staging_roots: list[Path] = []
    inbox_paths: list[Path] = []
    try:
        for session_id in session_ids:
            s._set_session_running(session_id, False)
            s._clear_session_turn_control(session_id)
            s._clear_session_live_output(session_id)
            s._invalidate_session_agent_runtime_cache(session_id)
            s._invalidate_session_conversation_events_cache(session_id)
        for agent in agents:
            agent_id = str(agent.get("agentId") or "").strip()
            direct_session_id = str(agent.get("directSessionId") or "").strip()
            # A direct binding is conversation-domain state even when an old
            # catalog/index row was already missing.  Leaving it would let the
            # directory materialize that disposable session again on first read.
            if agent_id and direct_session_id:
                direct_bindings_before[agent_id] = direct_session_id
                s.update_agent_instance(agent_id, direct_session_id="")
            inbox_path = s.agent_directory_service._agent_workspace_event_path(
                agent,
                "agent_inbox_messages.jsonl",
            )
            if inbox_path.exists():
                inbox_paths.append(inbox_path)

        nonce = s.secrets.token_hex(6)
        for sessions_root in s._agent_session_workspace_roots():
            staging_root = s._agent_session_purge_staging_root(
                sessions_root,
                agent_id="all-agent-test-conversations",
                nonce=nonce,
            )
            staging_roots.append(staging_root)
            s._write_agent_session_purge_manifest(
                staging_root,
                {
                    "version": 1,
                    "transactionId": nonce,
                    "agentId": "all-agent-test-conversations",
                    "state": "staged",
                    "sessionIds": session_ids,
                    "workspaceMoves": [],
                    "updatedAt": s._now_timestamp(),
                },
            )
            for session_id in session_ids:
                source = (sessions_root / s._safe_session_workspace_token(session_id)).resolve()
                if not source.is_relative_to(sessions_root) or not source.exists():
                    continue
                staging_root.mkdir(parents=True, exist_ok=True)
                destination = (staging_root / source.name).resolve()
                if not destination.is_relative_to(staging_root):
                    raise s.SessionValidationError(f"Invalid staged session workspace path: {destination}")
                shutil.move(str(source), str(destination))
                workspace_moves.append({"source": str(source), "staged": str(destination)})
        for inbox_path in inbox_paths:
            inbox_path.unlink()
    except Exception:
        for move in reversed(workspace_moves):
            try:
                s._restore_staged_agent_workspace_move(move)
            except Exception:
                pass
        for agent_id, direct_session_id in direct_bindings_before.items():
            try:
                s.update_agent_instance(agent_id, direct_session_id=direct_session_id)
            except Exception:
                pass
        if payload_before is not None:
            with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
                s.save_chat_state(s.PROJECT_ROOT, payload_before)
        raise

    cleanup = s.commit_staged_agent_session_purge({
        "agentId": "all-agent-test-conversations",
        "sessionIds": session_ids,
        "workspaceMoves": workspace_moves,
        "stagingRoots": [str(path) for path in staging_roots],
    })
    s._invalidate_session_list_cache()
    from . import directory_bridge

    for session_id in session_ids:
        directory_bridge.archive_directory_session_safe(session_id)
    result = {
        **cleanup,
        "agentBindingsCleared": len(direct_bindings_before),
        "inboxRecordsCleared": len(inbox_paths),
        "historyRetention": "deleted",
    }
    s._record_agent_session_lifecycle_event(
        "agent_test_conversations_reset",
        "conversation.agent_sessions.test_domain_reset",
        outcome="partial" if bool(result.get("cleanupPending")) else "succeeded",
        level="warning" if bool(result.get("cleanupPending")) else "info",
        fields={
            "deletedSessionCount": len(session_ids),
            "agentBindingsCleared": len(direct_bindings_before),
            "inboxRecordsCleared": len(inbox_paths),
            "workspaceDeletedCount": int(result.get("workspaceDeletedCount") or 0),
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
        dirty_rows = [
            dict(raw)
            for raw in conversations
            if isinstance(raw, dict)
            and str(raw.get("conversation_id") or "").strip() in selected
        ]
        activate_id = ""
        if active_id in selected:
            activate_id = str(payload.get("active_conversation_id") or "").strip()
            found = s._find_conversation_entry(payload, activate_id)
            if isinstance(found, dict) and activate_id not in selected:
                dirty_rows.append(dict(found))
        s._persist_dirty_session_runtime_rows(dirty_rows, activate_session_id=activate_id)
        archived_rows = [
            dict(raw)
            for raw in conversations
            if isinstance(raw, dict)
            and str(raw.get("conversation_id") or "").strip() in selected
        ]
        replacement_row = None
        active_after = str(payload.get("active_conversation_id") or "").strip()
        if active_after and active_after not in selected:
            found = s._find_conversation_entry(payload, active_after)
            replacement_row = dict(found) if isinstance(found, dict) else None
    from . import directory_bridge

    directory_bridge.sync_conversation_records(archived_rows)
    if replacement_row is not None:
        directory_bridge.sync_conversation_record(replacement_row)
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


# ---------------------------------------------------------------------------
# Challenge Cup team-scoped session reset
# ---------------------------------------------------------------------------
#
# This is intentionally kept in the session lifecycle owner.  The Challenge
# Cup reset coordinator can compose it with room/artifact/checkpoint ports,
# while this module remains responsible for exactly one source of truth:
# chat_state plus the session workspaces.  Agent definitions are never edited
# here.  A reset stage removes selected rows from the active projection, but
# keeps a private in-process restore token and managed staging directories
# until the coordinator explicitly purges and destroys them.

_TEAM_AGENT_SESSION_RESET_SCHEMA_VERSION = 1
_TEAM_AGENT_SESSION_RESET_OPERATION = "challenge_cup_team_agent_session_reset"
_TEAM_AGENT_SESSION_RESET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_TEAM_AGENT_SESSION_RESET_ACTIVE_PHASES = frozenset(
    {
        "queued",
        "starting",
        "dispatching",
        "running",
        "stopping",
        "paused",
        "waiting_human",
        "summarizing",
        "awaiting_approval",
        "collecting",
    }
)
_TEAM_AGENT_SESSION_RESET_STATES = frozenset(
    {"staged", "purged", "restored", "destroyed"}
)
_TEAM_AGENT_SESSION_RESET_STAGING_PREFIX = ".challenge-cup-session-reset-"
_TEAM_AGENT_SESSION_RESET_MANIFEST_NAME = "manifest.json"


class TeamAgentSessionResetError(RuntimeError):
    """Base error for the governed Challenge Cup session reset port."""

    code = "team_agent_session_reset_error"


class TeamAgentSessionResetValidationError(TeamAgentSessionResetError):
    code = "team_agent_session_reset_validation_error"


class TeamAgentSessionResetConflictError(TeamAgentSessionResetError):
    code = "team_agent_session_reset_conflict"


class TeamAgentSessionResetBusyError(TeamAgentSessionResetError):
    code = "team_agent_session_reset_busy"


def _team_agent_session_reset_scope(team_id: Any, reset_id: Any) -> tuple[str, str]:
    team = str(team_id or "").strip()
    reset = str(reset_id or "").strip()
    if not team or not _TEAM_AGENT_SESSION_RESET_KEY.fullmatch(team):
        raise TeamAgentSessionResetValidationError(
            "A safe team_id is required for the Agent session reset."
        )
    if not reset or not _TEAM_AGENT_SESSION_RESET_KEY.fullmatch(reset):
        raise TeamAgentSessionResetValidationError(
            "A safe reset_id is required for the Agent session reset."
        )
    return team, reset


def _team_agent_session_reset_agent_ids(agent_ids: Any) -> list[str]:
    if isinstance(agent_ids, (str, bytes, bytearray)):
        values = [agent_ids]
    elif isinstance(agent_ids, (list, tuple, set, frozenset)):
        values = list(agent_ids)
    else:
        values = []
    normalized = [str(value or "").strip() for value in values]
    if not normalized or any(
        not value or not _TEAM_AGENT_SESSION_RESET_KEY.fullmatch(value)
        for value in normalized
    ):
        raise TeamAgentSessionResetValidationError(
            "Explicit trusted Agent ids are required for the session reset."
        )
    if len(set(normalized)) != len(normalized):
        raise TeamAgentSessionResetValidationError(
            "Agent ids must be unique for the session reset."
        )
    return normalized


def _team_agent_session_reset_nested(item: Any, *keys: str) -> str:
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    for container_key in (
        "metadata",
        "scope",
        "binding",
        "teamBinding",
        "experimentBinding",
    ):
        nested = item.get(container_key)
        if not isinstance(nested, dict):
            continue
        for key in keys:
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    return ""


def _team_agent_session_reset_agent_owner(agent: dict[str, Any]) -> str:
    return _team_agent_session_reset_nested(
        agent,
        "teamId",
        "team_id",
        "ownerTeamId",
        "owner_team_id",
        "researchTeamId",
        "challengeCupTeamId",
    )


def _team_agent_session_reset_list_agents(s: Any, *, include_archived: bool) -> list[dict[str, Any]]:
    directory = getattr(s, "agent_directory_service", None)
    list_agents = getattr(directory, "list_agents", None)
    if not callable(list_agents):
        raise TeamAgentSessionResetValidationError(
            "Agent directory authority is unavailable."
        )
    try:
        rows = list_agents(include_archived=include_archived, detail="full")
    except TypeError:
        rows = list_agents(include_archived=include_archived)
    if not isinstance(rows, list):
        raise TeamAgentSessionResetValidationError(
            "Agent directory authority is malformed."
        )
    return [dict(row) for row in rows if isinstance(row, dict)]


def _team_agent_session_reset_validate_agents(
    s: Any,
    *,
    team_id: str,
    agent_ids: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    all_agents = _team_agent_session_reset_list_agents(s, include_archived=True)
    by_id = {
        str(row.get("agentId") or row.get("agent_id") or "").strip(): row
        for row in all_agents
        if str(row.get("agentId") or row.get("agent_id") or "").strip()
    }
    requested: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    for agent_id in agent_ids:
        agent = by_id.get(agent_id)
        if agent is None:
            getter = getattr(getattr(s, "agent_directory_service", None), "get_agent", None)
            if callable(getter):
                try:
                    candidate = getter(agent_id, include_archived=True)
                except TypeError:
                    candidate = getter(agent_id)
                if isinstance(candidate, dict):
                    agent = dict(candidate)
                    by_id[agent_id] = agent
        if agent is None:
            raise TeamAgentSessionResetValidationError(
                f"Trusted Agent is missing from the directory: {agent_id}"
            )
        owner = _team_agent_session_reset_agent_owner(agent)
        if not owner or owner != team_id:
            raise TeamAgentSessionResetValidationError(
                f"Agent {agent_id} has incomplete or mismatched team authority."
            )
        status = str(agent.get("status") or "active").strip().lower()
        if status in {"archived", "deleted", "inactive"}:
            raise TeamAgentSessionResetValidationError(
                f"Agent {agent_id} is not an active retained Agent."
            )
        direct_session_id = str(
            agent.get("directSessionId") or agent.get("direct_session_id") or ""
        ).strip()
        if not direct_session_id:
            raise TeamAgentSessionResetValidationError(
                f"Agent {agent_id} has no authoritative direct session binding."
            )
        requested[agent_id] = agent
        owners[agent_id] = owner
    # The owner map is also used to reject a selected child row whose Agent id
    # is known to belong to another team.  Do not infer ownership from a role
    # label or from a session id.
    for row in all_agents:
        row_id = str(row.get("agentId") or row.get("agent_id") or "").strip()
        owner = _team_agent_session_reset_agent_owner(row)
        if row_id and owner:
            owners.setdefault(row_id, owner)
    return requested, owners


def _team_agent_session_reset_session_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("conversation_id") or row.get("conversationId") or row.get("id") or "").strip()


def _team_agent_session_reset_agent_id(row: Any) -> str:
    return _team_agent_session_reset_nested(row, "agentId", "agent_id")


def _team_agent_session_reset_parent_id(row: Any) -> str:
    return _team_agent_session_reset_nested(row, "parentSessionId", "parent_session_id")


def _team_agent_session_reset_root_id(row: Any) -> str:
    return _team_agent_session_reset_nested(row, "rootSessionId", "root_session_id")


def _team_agent_session_reset_team_id(row: Any) -> str:
    return _team_agent_session_reset_nested(
        row,
        "teamId",
        "team_id",
        "ownerTeamId",
        "owner_team_id",
        "researchTeamId",
    )


def _team_agent_session_reset_phase(s: Any, session_id: str, row: dict[str, Any]) -> str:
    raw_status = str(
        row.get("last_turn_status")
        or row.get("lastTurnStatus")
        or row.get("status")
        or row.get("state")
        or ""
    ).strip().lower()
    if raw_status in _TEAM_AGENT_SESSION_RESET_ACTIVE_PHASES:
        return raw_status
    phase_fn = getattr(s, "_conversation_phase", None)
    normalize_fn = getattr(s, "_normalize_conversation", None)
    if not callable(phase_fn):
        return raw_status
    normalized = row
    if callable(normalize_fn):
        try:
            normalized = normalize_fn(
                row,
                agent_by_id=s._agent_lookup_for_conversations(),
                ensure_workspace=False,
                lightweight=True,
            ) or row
        except TypeError:
            normalized = normalize_fn(row, ensure_workspace=False, lightweight=True) or row
    try:
        return str(phase_fn(session_id, normalized) or raw_status).strip().lower()
    except Exception as exc:
        raise TeamAgentSessionResetValidationError(
            f"Session activity authority is unavailable for {session_id}."
        ) from exc


def _team_agent_session_reset_active_work(s: Any, selected: set[str]) -> None:
    list_active = getattr(s, "list_active_session_work_runs", None)
    if not callable(list_active):
        return
    try:
        raw = list_active(reconcile=False)
    except TypeError:
        raw = list_active()
    except Exception as exc:
        raise TeamAgentSessionResetValidationError(
            "Active-session authority is unavailable."
        ) from exc
    if isinstance(raw, dict):
        items = raw.get("activeItems") or raw.get("items") or raw.get("runs") or []
        try:
            reported_count = int(raw.get("activeCount") or raw.get("count") or 0)
        except (TypeError, ValueError):
            raise TeamAgentSessionResetValidationError(
                "Active-session authority has an invalid count."
            )
        if reported_count > 0 and not items:
            raise TeamAgentSessionResetValidationError(
                "Active-session authority reports work without session identities."
            )
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        raise TeamAgentSessionResetValidationError(
            "Active-session authority is malformed."
        )
    for item in items:
        if not isinstance(item, dict):
            raise TeamAgentSessionResetValidationError(
                "Active-session authority contains an invalid record."
            )
        session_id = str(
            item.get("sessionId")
            or item.get("session_id")
            or item.get("conversationId")
            or item.get("conversation_id")
            or ""
        ).strip()
        if session_id in selected:
            raise TeamAgentSessionResetBusyError(
                f"Session {session_id} still has active work."
            )


def _team_agent_session_reset_manifest_hash(manifest: dict[str, Any]) -> str:
    stable = {
        key: value
        for key, value in manifest.items()
        if key not in {
            "manifestHash",
            "status",
            "createdAt",
            "updatedAt",
            "purgedAt",
            "restoredAt",
            "destroyedAt",
            "previousConversations",
        }
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _team_agent_session_reset_manifest_path(staging_root: Path) -> Path:
    return staging_root / _TEAM_AGENT_SESSION_RESET_MANIFEST_NAME


def _team_agent_session_reset_staging_root(
    sessions_root: Path,
    *,
    team_id: str,
    reset_id: str,
) -> Path:
    s = _service()
    root = Path(sessions_root).resolve()
    token = f"{_TEAM_AGENT_SESSION_RESET_STAGING_PREFIX}{_safe_session_workspace_token(team_id)}-{_safe_session_workspace_token(reset_id)}"
    staging = (root / token).resolve()
    if not staging.is_relative_to(root):
        raise TeamAgentSessionResetValidationError(
            f"Invalid session reset staging path: {staging}"
        )
    return staging


def _team_agent_session_reset_staging_root_is_safe(
    staging_root: Path,
    *,
    allowed_roots: list[Path],
) -> bool:
    s = _service()
    return bool(
        staging_root.name.startswith(_TEAM_AGENT_SESSION_RESET_STAGING_PREFIX)
        and any(staging_root.parent == Path(root).resolve() for root in allowed_roots)
        and not staging_root.is_symlink()
        and not bool(getattr(s, "_path_is_reparse_point", lambda _path: False)(staging_root))
    )


def _team_agent_session_reset_write_manifest(
    staging_root: Path,
    manifest: dict[str, Any],
) -> None:
    s = _service()
    if not _team_agent_session_reset_staging_root_is_safe(
        staging_root,
        allowed_roots=s._agent_session_workspace_roots(),
    ):
        raise TeamAgentSessionResetValidationError(
            f"Unsafe session reset staging root: {staging_root}"
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    path = _team_agent_session_reset_manifest_path(staging_root)
    temporary = path.with_name(f"{path.name}.{s.secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _team_agent_session_reset_read_manifest(staging_root: Path) -> dict[str, Any]:
    path = _team_agent_session_reset_manifest_path(staging_root)
    if not path.is_file() or path.is_symlink():
        raise TeamAgentSessionResetValidationError(
            "Session reset staging manifest is missing."
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TeamAgentSessionResetValidationError(
            "Session reset staging manifest is unreadable."
        ) from exc
    if not isinstance(value, dict):
        raise TeamAgentSessionResetValidationError(
            "Session reset staging manifest must be an object."
        )
    return value


def _team_agent_session_reset_validate_token(
    stage: Any,
    *,
    team_id: str,
    reset_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(stage, dict):
        raise TeamAgentSessionResetValidationError(
            "A staged Agent session reset handle is required."
        )
    token = stage.get("restoreToken") if isinstance(stage.get("restoreToken"), dict) else stage
    if not isinstance(token, dict):
        raise TeamAgentSessionResetValidationError(
            "A staged Agent session reset restore token is missing."
        )
    if str(token.get("teamId") or "").strip() != team_id:
        raise TeamAgentSessionResetValidationError(
            "Agent session reset belongs to another team."
        )
    if str(token.get("resetId") or "").strip() != reset_id:
        raise TeamAgentSessionResetValidationError(
            "Agent session reset belongs to another reset."
        )
    if token.get("schemaVersion") != _TEAM_AGENT_SESSION_RESET_SCHEMA_VERSION:
        raise TeamAgentSessionResetValidationError(
            "Agent session reset schema version is invalid."
        )
    if token.get("operation") != _TEAM_AGENT_SESSION_RESET_OPERATION:
        raise TeamAgentSessionResetValidationError(
            "Agent session reset operation is invalid."
        )
    status = str(token.get("status") or "").strip().lower()
    if status not in _TEAM_AGENT_SESSION_RESET_STATES:
        raise TeamAgentSessionResetValidationError(
            f"Unsupported Agent session reset state: {status or 'missing'}"
        )
    expected_hash = str(token.get("manifestHash") or "").strip()
    if not expected_hash or expected_hash != _team_agent_session_reset_manifest_hash(token):
        raise TeamAgentSessionResetConflictError(
            "Agent session reset manifest hash is invalid."
        )
    session_ids = [str(value or "").strip() for value in list(token.get("sessionIds") or [])]
    if len(session_ids) != len(set(session_ids)) or any(not value for value in session_ids):
        raise TeamAgentSessionResetValidationError(
            "Agent session reset session identities are incomplete."
        )
    previous = list(token.get("previousConversations") or [])
    if len(previous) != len(session_ids):
        raise TeamAgentSessionResetValidationError(
            "Agent session reset restore authority is incomplete."
        )
    for item in previous:
        if not isinstance(item, dict) or not isinstance(item.get("conversation"), dict):
            raise TeamAgentSessionResetValidationError(
                "Agent session reset restore authority contains an invalid row."
            )
        if _team_agent_session_reset_session_id(item["conversation"]) not in session_ids:
            raise TeamAgentSessionResetConflictError(
                "Agent session reset restore row does not match its staged identity."
            )
    manifest = {
        key: value
        for key, value in token.items()
        if key not in {"previousConversations", "workspaceMoves"}
    }
    manifest["workspaceMoves"] = list(token.get("workspaceMoves") or [])
    return token, manifest


def _team_agent_session_reset_update_manifests(
    token: dict[str, Any],
    *,
    status: str,
    timestamp_key: str,
) -> None:
    manifest = {
        key: value
        for key, value in token.items()
        if key not in {"previousConversations", "workspaceMoves", "manifestHash"}
    }
    manifest["workspaceMoves"] = list(token.get("workspaceMoves") or [])
    manifest["status"] = status
    manifest[timestamp_key] = _service()._now_timestamp()
    manifest["updatedAt"] = manifest[timestamp_key]
    manifest["manifestHash"] = _team_agent_session_reset_manifest_hash(manifest)
    token["status"] = status
    token["manifestHash"] = manifest["manifestHash"]
    token[timestamp_key] = manifest[timestamp_key]
    token["updatedAt"] = manifest["updatedAt"]
    for staging_root_value in list(token.get("stagingRoots") or []):
        staging_root = Path(str(staging_root_value or "")).resolve()
        if staging_root.exists():
            _team_agent_session_reset_write_manifest(staging_root, manifest)


def _team_agent_session_reset_restore_chat_state(token: dict[str, Any]) -> bool:
    s = _service()
    session_ids = {
        str(value or "").strip()
        for value in list(token.get("sessionIds") or [])
        if str(value or "").strip()
    }
    if not session_ids:
        return False
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = [
            raw
            for raw in list(payload.get("conversations") or [])
            if isinstance(raw, dict)
            and _team_agent_session_reset_session_id(raw) not in session_ids
            and _team_agent_session_reset_session_id(raw)
            != str(token.get("createdReplacementSessionId") or "").strip()
        ]
        existing_ids = {
            _team_agent_session_reset_session_id(raw)
            for raw in conversations
            if _team_agent_session_reset_session_id(raw)
        }
        for item in sorted(
            (entry for entry in list(token.get("previousConversations") or []) if isinstance(entry, dict)),
            key=lambda entry: int(entry.get("index") or 0),
        ):
            raw = item.get("conversation")
            if not isinstance(raw, dict):
                continue
            session_id = _team_agent_session_reset_session_id(raw)
            if session_id in existing_ids:
                raise TeamAgentSessionResetConflictError(
                    f"Session {session_id} already exists during reset restore."
                )
            index = max(0, min(int(item.get("index") or 0), len(conversations)))
            conversations.insert(index, copy.deepcopy(raw))
            existing_ids.add(session_id)
        payload["conversations"] = conversations
        previous_active = str(token.get("previousActiveConversationId") or "").strip()
        payload["active_conversation_id"] = previous_active if previous_active in existing_ids else (
            str(payload.get("active_conversation_id") or "").strip()
            if str(payload.get("active_conversation_id") or "").strip() in existing_ids
            else (sorted(existing_ids)[0] if existing_ids else "")
        )
        previous_updated_at = str(token.get("previousUpdatedAt") or "").strip()
        payload["updated_at"] = previous_updated_at or s._now_timestamp()
        previous_version = token.get("previousVersion")
        payload["version"] = previous_version if isinstance(previous_version, int) else int(
            payload.get("version") or s.CHAT_STATE_VERSION
        )
        s.save_chat_state(s.PROJECT_ROOT, payload)
        restored_rows = [
            dict(raw)
            for raw in conversations
            if isinstance(raw, dict)
            and _team_agent_session_reset_session_id(raw) in session_ids
        ]
    from . import directory_bridge

    directory_bridge.sync_conversation_records(restored_rows)
    s._invalidate_session_list_cache()
    return True


def _team_agent_session_reset_move_workspaces_back(token: dict[str, Any]) -> None:
    for move in reversed(list(token.get("workspaceMoves") or [])):
        if not isinstance(move, dict):
            raise TeamAgentSessionResetValidationError(
                "Agent session reset workspace move is invalid."
            )
        source = Path(str(move.get("source") or "")).resolve()
        staged = Path(str(move.get("staged") or "")).resolve()
        source_exists = source.exists()
        staged_exists = staged.exists()
        if source_exists and staged_exists:
            raise TeamAgentSessionResetConflictError(
                f"Session workspace restore conflicts at {source}."
            )
        if source_exists and not staged_exists:
            continue
        if not staged_exists:
            raise TeamAgentSessionResetConflictError(
                f"Session workspace is missing from source and staging: {source}"
            )
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(source))
        if not source.exists() or staged.exists():
            raise TeamAgentSessionResetConflictError(
                f"Session workspace restore did not converge: {source}"
            )


def _team_agent_session_reset_move_workspaces_to_stage(token: dict[str, Any]) -> None:
    """Compensate a partial restore by moving already-restored roots back."""

    for move in list(token.get("workspaceMoves") or []):
        if not isinstance(move, dict):
            continue
        source = Path(str(move.get("source") or "")).resolve()
        staged = Path(str(move.get("staged") or "")).resolve()
        source_exists = source.exists()
        staged_exists = staged.exists()
        if source_exists and staged_exists:
            raise TeamAgentSessionResetConflictError(
                f"Session workspace compensation conflicts at {source}."
            )
        if not source_exists:
            continue
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(staged))
        if source.exists() or not staged.exists():
            raise TeamAgentSessionResetConflictError(
                f"Session workspace compensation did not converge: {staged}"
            )


def stage_team_agent_session_reset(
    team_id: str,
    agent_ids: list[str] | tuple[str, ...] | set[str],
    reset_id: str,
) -> dict[str, Any]:
    """Stage all direct/child sessions for explicit trusted team Agents.

    The operation is fail-closed: every Agent must have a current team owner
    and direct-session binding, every selected row must have an unambiguous
    identity, and any active turn/work-run blocks the stage.  Only chat rows
    and their session workspaces are touched; Agent definitions remain intact.
    """

    s = _service()
    team, reset = _team_agent_session_reset_scope(team_id, reset_id)
    requested_ids = _team_agent_session_reset_agent_ids(agent_ids)
    requested, owners = _team_agent_session_reset_validate_agents(
        s,
        team_id=team,
        agent_ids=requested_ids,
    )
    roots = [Path(root).resolve() for root in s._agent_session_workspace_roots()]
    staging_roots = [
        _team_agent_session_reset_staging_root(root, team_id=team, reset_id=reset)
        for root in roots
    ]
    for staging_root in staging_roots:
        if staging_root.exists() or staging_root.is_symlink():
            raise TeamAgentSessionResetConflictError(
                f"A session reset staging area already exists: {staging_root}"
            )

    timestamp = s._now_timestamp()
    previous_payload: dict[str, Any] | None = None
    workspace_moves: list[dict[str, str]] = []
    restore_token: dict[str, Any] | None = None
    session_ids: list[str] = []
    direct_session_ids = {
        agent_id: str(
            requested[agent_id].get("directSessionId")
            or requested[agent_id].get("direct_session_id")
            or ""
        ).strip()
        for agent_id in requested_ids
    }
    try:
        with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
            payload = s.load_chat_state(s.PROJECT_ROOT)
            previous_payload = copy.deepcopy(payload)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                raise TeamAgentSessionResetValidationError(
                    "Chat-state authority is missing its conversations list."
                )
            by_session: dict[str, dict[str, Any]] = {}
            for raw in conversations:
                if not isinstance(raw, dict):
                    raise TeamAgentSessionResetValidationError(
                        "Chat-state authority contains a non-object conversation."
                    )
                session_id = _team_agent_session_reset_session_id(raw)
                if not session_id:
                    raise TeamAgentSessionResetValidationError(
                        "Chat-state authority contains a conversation without an id."
                    )
                if session_id in by_session:
                    raise TeamAgentSessionResetConflictError(
                        f"Chat-state authority duplicates session {session_id}."
                    )
                by_session[session_id] = raw
            for agent_id, direct_id in direct_session_ids.items():
                if direct_id not in by_session:
                    raise TeamAgentSessionResetValidationError(
                        f"Direct session authority is missing for Agent {agent_id}: {direct_id}"
                    )
                row_agent_id = _team_agent_session_reset_agent_id(by_session[direct_id])
                if row_agent_id and row_agent_id != agent_id:
                    raise TeamAgentSessionResetConflictError(
                        f"Direct session {direct_id} is bound to another Agent."
                    )
                row_team_id = _team_agent_session_reset_team_id(by_session[direct_id])
                if row_team_id and row_team_id != team:
                    raise TeamAgentSessionResetConflictError(
                        f"Direct session {direct_id} belongs to another team."
                    )

            selected: set[str] = set(direct_session_ids.values())
            changed = True
            while changed:
                changed = False
                for session_id, raw in by_session.items():
                    row_agent_id = _team_agent_session_reset_agent_id(raw)
                    parent_id = _team_agent_session_reset_parent_id(raw)
                    root_id = _team_agent_session_reset_root_id(raw)
                    linked = row_agent_id in requested or parent_id in selected or root_id in selected
                    if not linked or session_id in selected:
                        continue
                    selected.add(session_id)
                    changed = True
            for session_id in sorted(selected):
                raw = by_session.get(session_id)
                if raw is None:
                    raise TeamAgentSessionResetValidationError(
                        f"Selected session authority is missing: {session_id}"
                    )
                row_team_id = _team_agent_session_reset_team_id(raw)
                if row_team_id and row_team_id != team:
                    raise TeamAgentSessionResetConflictError(
                        f"Session {session_id} belongs to another team."
                    )
                row_agent_id = _team_agent_session_reset_agent_id(raw)
                owner = owners.get(row_agent_id) if row_agent_id else team
                if row_agent_id and not owner:
                    raise TeamAgentSessionResetValidationError(
                        f"Session {session_id} has an Agent without team authority."
                    )
                if owner and owner != team:
                    raise TeamAgentSessionResetConflictError(
                        f"Session {session_id} is attached to another team Agent."
                    )
                phase = _team_agent_session_reset_phase(s, session_id, raw)
                if phase in _TEAM_AGENT_SESSION_RESET_ACTIVE_PHASES:
                    raise TeamAgentSessionResetBusyError(
                        f"Session {session_id} still has active work ({phase})."
                    )
            _team_agent_session_reset_active_work(s, selected)
            session_ids = [
                _team_agent_session_reset_session_id(raw)
                for raw in conversations
                if _team_agent_session_reset_session_id(raw) in selected
            ]
            restore_token = {
                "schemaVersion": _TEAM_AGENT_SESSION_RESET_SCHEMA_VERSION,
                "operation": _TEAM_AGENT_SESSION_RESET_OPERATION,
                "teamId": team,
                "resetId": reset,
                "status": "staged",
                "agentIds": list(requested_ids),
                "directSessionIds": dict(direct_session_ids),
                "sessionIds": list(session_ids),
                "sessionCount": len(session_ids),
                "previousConversations": [
                    {
                        "index": index,
                        "conversation": copy.deepcopy(raw),
                    }
                    for index, raw in enumerate(conversations)
                    if isinstance(raw, dict)
                    and _team_agent_session_reset_session_id(raw) in selected
                ],
                "previousActiveConversationId": str(payload.get("active_conversation_id") or "").strip(),
                "previousUpdatedAt": str(payload.get("updated_at") or "").strip(),
                "previousVersion": payload.get("version"),
                "createdReplacementSessionId": "",
                "workspaceMoves": [],
                "stagingRoots": [str(root) for root in staging_roots],
                "createdAt": timestamp,
                "updatedAt": timestamp,
            }
            payload["conversations"] = [
                raw
                for raw in conversations
                if _team_agent_session_reset_session_id(raw) not in selected
            ]
            active_id = str(payload.get("active_conversation_id") or "").strip()
            if active_id in selected:
                replacement_id = _replacement_session_after_agent_session_removal(
                    payload,
                    removed_session_ids=selected,
                    timestamp=timestamp,
                )
                payload["active_conversation_id"] = replacement_id
                if replacement_id not in selected and replacement_id not in by_session:
                    restore_token["createdReplacementSessionId"] = replacement_id
            payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
            payload["updated_at"] = timestamp
            s.save_chat_state(s.PROJECT_ROOT, payload)

        for session_id in session_ids:
            s._set_session_running(session_id, False)
            s._clear_session_turn_control(session_id)
            s._clear_session_live_output(session_id)
            s._invalidate_session_agent_runtime_cache(session_id)
            s._invalidate_session_conversation_events_cache(session_id)
        for sessions_root, staging_root in zip(roots, staging_roots, strict=True):
            root_moves: list[dict[str, str]] = []
            for session_id in session_ids:
                source = (sessions_root / s._safe_session_workspace_token(session_id)).resolve()
                if not source.is_relative_to(sessions_root):
                    raise TeamAgentSessionResetValidationError(
                        f"Invalid session workspace path: {source}"
                    )
                if not source.exists():
                    continue
                if source.is_symlink() or bool(getattr(s, "_path_is_reparse_point", lambda _path: False)(source)):
                    raise TeamAgentSessionResetValidationError(
                        f"Session workspace is a reparse point: {source}"
                    )
                staging_root.mkdir(parents=True, exist_ok=True)
                destination = (staging_root / source.name).resolve()
                if not destination.is_relative_to(staging_root) or destination.exists():
                    raise TeamAgentSessionResetConflictError(
                        f"Session workspace staging destination is unsafe: {destination}"
                    )
                move = {"source": str(source), "staged": str(destination)}
                root_moves.append(move)
                workspace_moves.append(move)
                shutil.move(str(source), str(destination))
        restore_token["workspaceMoves"] = workspace_moves
        restore_token["manifestHash"] = _team_agent_session_reset_manifest_hash(restore_token)
        manifest = dict(restore_token)
        manifest.pop("previousConversations", None)
        for staging_root in staging_roots:
            _team_agent_session_reset_write_manifest(staging_root, manifest)
    except Exception as exc:
        for move in reversed(workspace_moves):
            try:
                source = Path(move["source"])
                staged = Path(move["staged"])
                if not source.exists() and staged.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(staged), str(source))
            except Exception:
                pass
        if previous_payload is not None:
            try:
                with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
                    s.save_chat_state(s.PROJECT_ROOT, previous_payload)
            except Exception as rollback_error:
                raise TeamAgentSessionResetConflictError(
                    "Session reset staging failed and chat-state rollback was incomplete."
                ) from rollback_error
        for staging_root in staging_roots:
            try:
                if staging_root.exists():
                    shutil.rmtree(staging_root)
            except Exception:
                pass
        raise exc

    for session_id in session_ids:
        try:
            from . import directory_bridge

            directory_bridge.archive_directory_session_safe(session_id)
        except Exception:
            pass
    s._invalidate_session_list_cache()
    _team_agent_session_reset_event(
        s,
        "staged",
        team_id=team,
        reset_id=reset,
        agent_ids=requested_ids,
        session_ids=session_ids,
    )
    return {
        "status": "staged",
        "schemaVersion": _TEAM_AGENT_SESSION_RESET_SCHEMA_VERSION,
        "operation": _TEAM_AGENT_SESSION_RESET_OPERATION,
        "teamId": team,
        "resetId": reset,
        "agentIds": list(requested_ids),
        "sessionIds": list(session_ids),
        "directSessionIds": dict(direct_session_ids),
        "sessionCount": len(session_ids),
        "workspaceStagedCount": len(workspace_moves),
        "workspaceMoves": list(workspace_moves),
        "stagingRoots": [str(root) for root in staging_roots],
        "manifestHash": restore_token["manifestHash"],
        "restoreToken": restore_token,
    }


def purge_team_agent_session_reset(
    team_id: str,
    reset_id: str,
    stage: dict[str, Any],
) -> dict[str, Any]:
    """Commit a staged team session reset while keeping restore material."""

    s = _service()
    team, reset = _team_agent_session_reset_scope(team_id, reset_id)
    token, _manifest = _team_agent_session_reset_validate_token(
        stage,
        team_id=team,
        reset_id=reset,
    )
    status = str(token.get("status") or "").strip().lower()
    if status == "purged":
        return _team_agent_session_reset_summary(token)
    if status != "staged":
        raise TeamAgentSessionResetValidationError(
            "Only a staged Agent session reset can be purged."
        )
    selected = set(str(value or "").strip() for value in list(token.get("sessionIds") or []))
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
    current_ids = {
        _team_agent_session_reset_session_id(raw)
        for raw in list(payload.get("conversations") or [])
        if isinstance(raw, dict)
    }
    if selected & current_ids:
        raise TeamAgentSessionResetConflictError(
            "A staged Agent session was recreated before purge."
        )
    _team_agent_session_reset_active_work(s, selected)
    _team_agent_session_reset_update_manifests(
        token,
        status="purged",
        timestamp_key="purgedAt",
    )
    _team_agent_session_reset_event(
        s,
        "purged",
        team_id=team,
        reset_id=reset,
        agent_ids=list(token.get("agentIds") or []),
        session_ids=list(token.get("sessionIds") or []),
    )
    return _team_agent_session_reset_summary(token)


def restore_team_agent_session_reset(
    team_id: str,
    reset_id: str,
    stage: dict[str, Any],
) -> dict[str, Any]:
    """Restore chat rows and workspaces from a staged or purged reset."""

    s = _service()
    team, reset = _team_agent_session_reset_scope(team_id, reset_id)
    token, _manifest = _team_agent_session_reset_validate_token(
        stage,
        team_id=team,
        reset_id=reset,
    )
    status = str(token.get("status") or "").strip().lower()
    if status == "restored":
        return _team_agent_session_reset_summary(token)
    if status in {"destroyed"}:
        raise TeamAgentSessionResetValidationError(
            "A destroyed Agent session reset cannot be restored."
        )
    if status not in {"staged", "purged"}:
        raise TeamAgentSessionResetValidationError(
            "Only a staged or purged Agent session reset can be restored."
        )
    before_restore_payload: dict[str, Any] | None = None
    try:
        with s._CHAT_STATE_LOCK:
            before_restore_payload = copy.deepcopy(s.load_chat_state(s.PROJECT_ROOT))
        _team_agent_session_reset_restore_chat_state(token)
        _team_agent_session_reset_move_workspaces_back(token)
    except Exception as exc:
        compensation_errors: list[str] = []
        try:
            _team_agent_session_reset_move_workspaces_to_stage(token)
        except Exception as compensation_error:
            compensation_errors.append(type(compensation_error).__name__)
        if before_restore_payload is not None:
            try:
                with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
                    s.save_chat_state(s.PROJECT_ROOT, before_restore_payload)
            except Exception as compensation_error:
                compensation_errors.append(type(compensation_error).__name__)
        if compensation_errors:
            raise TeamAgentSessionResetConflictError(
                "Agent session reset restore failed and compensation was incomplete: "
                + ", ".join(compensation_errors)
            ) from exc
        raise TeamAgentSessionResetConflictError(
            "Agent session reset restore failed; staged authority was retained."
        ) from exc
    _team_agent_session_reset_update_manifests(
        token,
        status="restored",
        timestamp_key="restoredAt",
    )
    _team_agent_session_reset_event(
        s,
        "restored",
        team_id=team,
        reset_id=reset,
        agent_ids=list(token.get("agentIds") or []),
        session_ids=list(token.get("sessionIds") or []),
    )
    return _team_agent_session_reset_summary(token)


def destroy_team_agent_session_reset(
    team_id: str,
    reset_id: str,
    stage: dict[str, Any],
) -> dict[str, Any]:
    """Permanently destroy staged workspace data after a successful purge."""

    s = _service()
    team, reset = _team_agent_session_reset_scope(team_id, reset_id)
    token, _manifest = _team_agent_session_reset_validate_token(
        stage,
        team_id=team,
        reset_id=reset,
    )
    status = str(token.get("status") or "").strip().lower()
    if status == "destroyed":
        return _team_agent_session_reset_summary(token)
    if status != "purged":
        raise TeamAgentSessionResetValidationError(
            "Only a purged Agent session reset can be destroyed."
        )
    selected = set(str(value or "").strip() for value in list(token.get("sessionIds") or []))
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
    current_ids = {
        _team_agent_session_reset_session_id(raw)
        for raw in list(payload.get("conversations") or [])
        if isinstance(raw, dict)
    }
    if selected & current_ids:
        raise TeamAgentSessionResetConflictError(
            "Active chat state still contains a session selected for destruction."
        )
    for move in list(token.get("workspaceMoves") or []):
        staged = Path(str(move.get("staged") or "")).resolve()
        if staged.exists() and (staged.is_symlink() or bool(getattr(s, "_path_is_reparse_point", lambda _path: False)(staged))):
            raise TeamAgentSessionResetValidationError(
                f"Session workspace staging is a reparse point: {staged}"
            )
    destroyed_count = 0
    try:
        for staging_root_value in list(token.get("stagingRoots") or []):
            staging_root = Path(str(staging_root_value or "")).resolve()
            if not _team_agent_session_reset_staging_root_is_safe(
                staging_root,
                allowed_roots=s._agent_session_workspace_roots(),
            ):
                raise TeamAgentSessionResetValidationError(
                    f"Unsafe session reset staging root: {staging_root}"
                )
            if staging_root.exists():
                shutil.rmtree(staging_root)
                destroyed_count += 1
    except Exception as exc:
        raise TeamAgentSessionResetConflictError(
            "Agent session reset staging cleanup is incomplete."
        ) from exc
    _team_agent_session_reset_update_manifests(
        token,
        status="destroyed",
        timestamp_key="destroyedAt",
    )
    _team_agent_session_reset_event(
        s,
        "destroyed",
        team_id=team,
        reset_id=reset,
        agent_ids=list(token.get("agentIds") or []),
        session_ids=list(token.get("sessionIds") or []),
    )
    result = _team_agent_session_reset_summary(token)
    result["workspaceDestroyedCount"] = destroyed_count
    return result


def _team_agent_session_reset_summary(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(token.get("status") or "").strip(),
        "schemaVersion": _TEAM_AGENT_SESSION_RESET_SCHEMA_VERSION,
        "operation": _TEAM_AGENT_SESSION_RESET_OPERATION,
        "teamId": str(token.get("teamId") or "").strip(),
        "resetId": str(token.get("resetId") or "").strip(),
        "agentIds": list(token.get("agentIds") or []),
        "sessionIds": list(token.get("sessionIds") or []),
        "directSessionIds": dict(token.get("directSessionIds") or {}),
        "sessionCount": len(list(token.get("sessionIds") or [])),
        "workspaceStagedCount": len(list(token.get("workspaceMoves") or [])),
        "stagingRoots": list(token.get("stagingRoots") or []),
        "manifestHash": str(token.get("manifestHash") or "").strip(),
        "restoreToken": token,
    }


def _team_agent_session_reset_event(
    s: Any,
    phase: str,
    *,
    team_id: str,
    reset_id: str,
    agent_ids: list[str],
    session_ids: list[str],
) -> None:
    try:
        s._record_agent_session_lifecycle_event(
            "challenge_cup_team_reset",
            f"conversation.agent_sessions.team_reset_{phase}",
            fields={
                "teamId": team_id,
                "resetId": reset_id,
                "agentIds": list(agent_ids)[:20],
                "sessionCount": len(session_ids),
                "sessionIds": list(session_ids)[:20],
            },
        )
    except Exception:
        return


# Names used by reset adapters.  Keep one implementation and expose explicit
# aliases so the cross-store coordinator can call the same lifecycle vocabulary
# as the artifact/checkpoint ports without reaching into private helpers.
stage_team_agent_sessions = stage_team_agent_session_reset
purge_team_agent_sessions = purge_team_agent_session_reset
commit_team_agent_session_reset = purge_team_agent_session_reset
commit_team_agent_sessions = purge_team_agent_session_reset
restore_team_agent_sessions = restore_team_agent_session_reset
destroy_team_agent_sessions = destroy_team_agent_session_reset


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
    switch_to_child: bool = False,
    source: str = "agent_auto_split",
    experiment_binding: dict[str, Any] | None = None,
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
        source_parent = s.load_session_chat_state(s.PROJECT_ROOT, parent_id)
        if source_parent is None:
            if s._ensure_agent_directory_conversation_materialized(
                parent_id,
                source="s.create_child_session",
            ):
                source_parent = s.load_session_chat_state(s.PROJECT_ROOT, parent_id)
        if source_parent is None:
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到父会话。", en="Parent session not found."))
        s._ensure_session_mutable(parent_id, conversation=source_parent)
        s._ensure_conversation_workspace_metadata(source_parent)
        s._ensure_conversation_agent_metadata(source_parent)
        normalized_parent = s._normalize_conversation(source_parent, ensure_workspace=False)
        root_id = str((normalized_parent or {}).get("rootSessionId") or parent_id).strip() or parent_id
        if str((normalized_parent or {}).get("sessionKind") or "main") == "child":
            root_id = str((normalized_parent or {}).get("rootSessionId") or (normalized_parent or {}).get("parentSessionId") or parent_id).strip() or parent_id
        parent = source_parent
        if root_id != parent_id:
            parent = s.load_session_chat_state(s.PROJECT_ROOT, root_id) or source_parent
        s._ensure_conversation_workspace_metadata(parent)
        s._ensure_conversation_agent_metadata(parent)
        existing_ids = set(s.list_session_runtime_ids(s.PROJECT_ROOT))
        now = s._now_timestamp()
        child_id = s._new_conversation_id(existing_ids)
        title = s.trim_lines(task_title or request_text, max_lines=1).strip() or s.text_for(lang, zh="子对话", en="Child session")
        agent_id = str(parent.get("agent_id") or parent.get("agentId") or "").strip()
        raw_experiment_binding = (
            experiment_binding if isinstance(experiment_binding, dict) else {}
        )
        normalized_experiment_binding: dict[str, Any] = {}
        if raw_experiment_binding:
            try:
                binding_attempt = max(1, int(raw_experiment_binding.get("attempt") or 1))
            except (TypeError, ValueError):
                binding_attempt = 1
            normalized_experiment_binding = {
                "teamId": str(raw_experiment_binding.get("teamId") or "").strip()[:160],
                "researchProjectId": str(
                    raw_experiment_binding.get("researchProjectId") or ""
                ).strip()[:160],
                "experimentName": str(
                    raw_experiment_binding.get("experimentName") or ""
                ).strip()[:160],
                "agentId": str(raw_experiment_binding.get("agentId") or "").strip()[:160],
                "roleKey": str(raw_experiment_binding.get("roleKey") or "").strip()[:80],
                "roleLabel": str(raw_experiment_binding.get("roleLabel") or "").strip()[:80],
                "attempt": binding_attempt,
                "retryOfSessionId": str(
                    raw_experiment_binding.get("retryOfSessionId") or ""
                ).strip()[:160],
                "createdFromTaskId": str(
                    raw_experiment_binding.get("createdFromTaskId") or ""
                ).strip()[:160],
                "createdAt": str(raw_experiment_binding.get("createdAt") or "").strip()[:120],
            }
            workflow_run_id = str(
                raw_experiment_binding.get("workflowRunId") or ""
            ).strip()[:160]
            workflow_node_id = str(
                raw_experiment_binding.get("workflowNodeId") or ""
            ).strip()[:80]
            if bool(workflow_run_id) != bool(workflow_node_id):
                raise s.SessionValidationError(
                    "Child experiment binding workflow scope requires both workflowRunId and workflowNodeId."
                )
            if workflow_run_id and workflow_node_id:
                normalized_experiment_binding["workflowRunId"] = workflow_run_id
                normalized_experiment_binding["workflowNodeId"] = workflow_node_id
            selection_id = str(raw_experiment_binding.get("selectionId") or "").strip()[:160]
            candidate_id = str(raw_experiment_binding.get("candidateId") or "").strip()[:160]
            if bool(selection_id) != bool(candidate_id):
                raise s.SessionValidationError(
                    "Child experiment binding candidate scope requires both selectionId and candidateId."
                )
            if selection_id and candidate_id:
                normalized_experiment_binding["selectionId"] = selection_id
                normalized_experiment_binding["candidateId"] = candidate_id
            raw_scope = raw_experiment_binding.get("scope")
            if isinstance(raw_scope, dict):
                scope = {
                    key: raw_scope[key]
                    for key in (
                        "version",
                        "kind",
                        "teamId",
                        "researchProjectId",
                        "agentId",
                        "workflowRunId",
                        "workflowNodeId",
                        "selectionId",
                        "candidateId",
                    )
                    if key in raw_scope and key not in {"attempt"}
                }
                if scope:
                    normalized_experiment_binding["scope"] = scope
            from .discussion_scope_binding import (
                DiscussionScopeBindingError,
                normalize_discussion_scope_binding,
            )

            try:
                normalized_experiment_binding.update(
                    normalize_discussion_scope_binding(
                        raw_experiment_binding,
                        team_id=normalized_experiment_binding["teamId"],
                        research_project_id=normalized_experiment_binding["researchProjectId"],
                        workflow_run_id=workflow_run_id,
                        workflow_node_id=workflow_node_id,
                        selection_id=selection_id,
                        candidate_id=candidate_id,
                    )
                )
            except DiscussionScopeBindingError as exc:
                raise s.SessionValidationError(str(exc)) from exc
            binding_agent_id = str(normalized_experiment_binding.get("agentId") or "").strip()
            if binding_agent_id and binding_agent_id != agent_id:
                raise s.SessionValidationError(
                    "Child experiment binding Agent id does not match the parent Agent."
                )
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
        if normalized_experiment_binding:
            child["experiment_binding"] = normalized_experiment_binding
            child["experimentBinding"] = normalized_experiment_binding
        s._ensure_conversation_workspace_metadata(child)
        child_ids = s._normalize_string_list(parent.get("child_session_ids") or parent.get("childSessionIds"))
        if child_id not in child_ids:
            child_ids.append(child_id)
        parent["child_session_ids"] = child_ids
        parent["active_child_session_id"] = child_id
        parent.pop("messages", None)
        parent["updated_at"] = now
        dirty_rows = [parent, child]
        parent_session_id = str(parent.get("conversation_id") or root_id).strip() or root_id
        if parent_session_id != parent_id:
            dirty_rows.append(source_parent)
        s._persist_dirty_session_runtime_rows(
            dirty_rows,
            activate_session_id=child_id if switch_to_child else "",
        )
        parent_snapshot = dict(parent)
        child_snapshot = dict(child)
    from . import directory_bridge

    directory_bridge.sync_conversation_record(parent_snapshot)
    directory_bridge.sync_conversation_record(
        child_snapshot,
        last_preview=request_text,
        status="queued" if auto_start else "ready",
    )
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
    started_at = s._perf_counter()
    chat_state_wait_started_at = s._perf_counter()
    with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
        chat_state_wait_ms = s._elapsed_ms(chat_state_wait_started_at)
        chat_state_read_started_at = s._perf_counter()
        payload = s.load_chat_state(s.PROJECT_ROOT)
        chat_state_read_ms = s._elapsed_ms(chat_state_read_started_at)
        relationship_scan_started_at = s._perf_counter()
        conversations = [
            raw
            for raw in list(payload.get("conversations") or [])
            if isinstance(raw, dict)
        ]
        source = next(
            (
                raw
                for raw in conversations
                if str(raw.get("conversation_id") or raw.get("id") or "").strip()
                == normalized_session_id
            ),
            None,
        )
        root_id = (
            s._raw_conversation_root_session_id(source, normalized_session_id)
            if source is not None
            else normalized_session_id
        )
        child_records = [
            dict(raw)
            for raw in conversations
            if s._raw_conversation_session_kind(raw) == "child"
            and str(raw.get("parent_session_id") or raw.get("parentSessionId") or "").strip()
            == root_id
        ]
        relationship_scan_ms = s._elapsed_ms(relationship_scan_started_at)

    child_projection_started_at = s._perf_counter()
    children: list[dict[str, Any]] = []
    if child_records:
        agent_by_id = s._agent_lookup_for_conversations()
        hidden_team_member_agent_ids = s._agent_directory_stub_hidden_team_member_ids()
        for raw in child_records:
            conversation = s._normalize_conversation(
                raw,
                agent_by_id=agent_by_id,
                hidden_team_member_agent_ids=hidden_team_member_agent_ids,
                ensure_workspace=False,
                lightweight=True,
            )
            if conversation is not None:
                children.append(s._build_session_summary(conversation, hydrate_agent=False))
    children.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    child_projection_ms = s._elapsed_ms(child_projection_started_at)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_child_list",
            "session.child_list.loaded",
            level="info",
            outcome="observed",
            message="Child sessions loaded through the read-only lightweight relationship index.",
            fields={
                "requestedSessionId": normalized_session_id,
                "rootSessionId": root_id,
                "resultCount": len(children),
                "elapsedMs": s._elapsed_ms(started_at),
                "readOnly": True,
                "projectionSource": "lightweight_child_relationship_index",
                "chatStateWaitMs": chat_state_wait_ms,
                "chatStateReadMs": chat_state_read_ms,
                "relationshipScanMs": relationship_scan_ms,
                "childProjectionMs": child_projection_ms,
            },
            lifecycle=False,
        )
    except Exception:
        pass
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
        existing_ids = set(s.list_session_runtime_ids(s.PROJECT_ROOT))
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
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
        created_supervised = dict(conversation)
    from . import directory_bridge

    directory_bridge.sync_conversation_record(created_supervised)
    s._invalidate_session_list_cache()
    return s.get_session_detail(session_id) or {}


def delete_chat_session(session_id: str) -> dict[str, Any]:
    """Delete one chat session and return a lightweight UI handoff payload."""
    return delete_chat_session_lightweight(session_id)


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
    fallback_title = s.text_for(lang, zh="新会话", en="New session")
    try:
        s._sync_agent_directory_project_root()
        agent_row = s.get_agent(normalized_agent_id, include_archived=False)
        if isinstance(agent_row, dict):
            agent_name = str(
                agent_row.get("displayName")
                or agent_row.get("agentCode")
                or agent_row.get("name")
                or ""
            ).strip()
            if agent_name:
                fallback_title = s.trim_lines(agent_name, max_lines=1).strip()[:120] or fallback_title
    except Exception:
        pass
    normalized_title = s.trim_lines(title or "", max_lines=1).strip() or fallback_title
    try:
        with s._CHAT_STATE_LOCK:
            s._ensure_agent_directory_conversation_materialized(
                old_session_id,
                source="agent_reset_direct_session",
            )
            old_conversation = s.load_session_chat_state(s.PROJECT_ROOT, old_session_id)
            if old_conversation is None:
                raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
            if s._repair_stale_running_conversation(old_conversation):
                s.save_session_chat_state(s.PROJECT_ROOT, old_session_id, old_conversation)
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
            existing_ids = set(s.list_session_runtime_ids(s.PROJECT_ROOT))
            replacement_session_id = s._new_conversation_id(existing_ids | {old_session_id})
            replacement_conversation = s._make_empty_conversation(
                replacement_session_id,
                title=normalized_title,
                timestamp=created_at,
            )
            s._ensure_conversation_workspace_metadata(replacement_conversation)
            replacement_conversation["agent_id"] = normalized_agent_id
            replacement_conversation["agentId"] = normalized_agent_id
            s.save_session_chat_state(
                s.PROJECT_ROOT,
                replacement_session_id,
                replacement_conversation,
                activate=True,
            )
            replacement_snapshot = dict(replacement_conversation)
        s._invalidate_session_list_cache()
        from . import directory_bridge

        directory_bridge.sync_conversation_record(replacement_snapshot)

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
            conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
            if include_restore_token:
                restore_token = {
                    "sessionId": normalized_session_id,
                    "agentId": normalized_agent_id,
                    "previousConversation": None,
                    "previousActiveConversationId": s.load_active_conversation_id(s.PROJECT_ROOT),
                    "previousUpdatedAt": "",
                    "previousVersion": None,
                }
            if conversation is not None:
                found = True
                if restore_token is not None:
                    restore_token["previousConversation"] = s.copy.deepcopy(conversation)
                changed = s._mark_conversation_agent_deleted(
                    conversation,
                    session_id=normalized_session_id,
                    agent_id=normalized_agent_id,
                    agent_display_name=agent_display_name,
                    previous_status=previous_status,
                    hide_from_index=hide_from_index,
                    timestamp=now,
                ) or changed
            else:
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
                changed = True
            if changed and conversation is not None:
                s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
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
    """Wake the collaboration target session so it can answer an inbox message.

    ADR 0002: prefer explicit ``message.targetSessionId`` (session landing) over
    rewriting to the Agent's current direct session.
    """
    s = _service()

    message_id = str(message.get("messageId") or message.get("eventId") or "").strip()
    target_agent_id = str(message.get("targetAgentId") or "").strip()
    target_agent = s.get_agent(target_agent_id, include_archived=False) if target_agent_id else None
    archived_target_agent = None if target_agent else (s.get_agent(target_agent_id, include_archived=True) if target_agent_id else None)
    persisted_target_session_id = str(message.get("targetSessionId") or "").strip()
    current_target_session_id = str((target_agent or {}).get("directSessionId") or "").strip()
    # Prefer explicit session landing; only fall back to direct when unset.
    target_session_id = persisted_target_session_id or (
        current_target_session_id
        if target_agent
        else str((archived_target_agent or {}).get("directSessionId") or "").strip()
    )
    # If an explicit session was set, verify it still exists; else fall back to direct.
    redirected_from_missing_session = False
    if persisted_target_session_id:
        try:
            detail = s.get_session_detail(persisted_target_session_id, message_limit=0, transcript_scope="none")
        except Exception:
            detail = None
        previous_target_session_id = ""
        target_agent_metadata = (target_agent or {}).get("metadata")
        if isinstance(target_agent_metadata, dict):
            previous_target_session_id = str(target_agent_metadata.get("previousDirectSessionId") or "").strip()
        # ADR 0002 prefers the explicit session landing, but a replaced direct
        # session (previousDirectSessionId) is a rebuild seam: wake the current
        # session instead of the stale one the message was addressed to.
        stale_replaced_session = bool(
            previous_target_session_id
            and previous_target_session_id == persisted_target_session_id
            and current_target_session_id
            and current_target_session_id != persisted_target_session_id
        )
        if not detail or stale_replaced_session:
            redirected_from_missing_session = True
            target_session_id = current_target_session_id or persisted_target_session_id
        else:
            owner_agent_id = str(detail.get("agentId") or "").strip()
            if owner_agent_id and target_agent_id and owner_agent_id != target_agent_id:
                # Do not wake a foreign session; fail closed.
                delivery = {
                    "wakeRequested": True,
                    "wakeStatus": "skipped_invalid_session",
                    "messageId": message_id,
                    "targetAgentId": target_agent_id,
                    "targetSessionId": persisted_target_session_id,
                    "persistedTargetSessionId": persisted_target_session_id,
                    "targetSessionRedirected": False,
                    "turnId": "",
                    "reason": "session_agent_mismatch",
                }
                s._record_agent_inbox_wake_event("agent_inbox.wake_skipped", message, delivery, level="warning")
                return delivery
            target_session_id = persisted_target_session_id
    delivery = {
        "wakeRequested": True,
        "wakeStatus": "skipped",
        "messageId": message_id,
        "targetAgentId": target_agent_id,
        "targetSessionId": target_session_id,
        "persistedTargetSessionId": persisted_target_session_id,
        "targetSessionRedirected": bool(redirected_from_missing_session),
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
        "repairDurationMs": 0,
        "agentScanDurationMs": 0,
        "agentRegistryLoadDurationMs": 0,
        "inboxSignatureDurationMs": 0,
        "inboxReadDurationMs": 0,
        "nonEmptyInboxCount": 0,
        "wakeableMessageCount": 0,
    }
    repair_started_at: float | None = None
    agent_scan_started_at: float | None = None
    try:
        # A restarted process owns no in-memory turns, so repair stale persisted
        # turn markers before submitting recovered inbox work to the scheduler.
        repair_started_at = s._perf_counter()
        with s._CHAT_STATE_LOCK, s.chat_state_transaction(s.PROJECT_ROOT):
            payload = s.load_chat_state(s.PROJECT_ROOT)
            s._repair_stale_running_conversations(payload)
        summary["repairDurationMs"] = s._elapsed_ms(repair_started_at)

        agent_scan_started_at = s._perf_counter()
        scan = s.agent_directory_service.scan_wakeable_agent_inbox_messages()
        for field in (
            "scannedAgentCount",
            "agentRegistryLoadDurationMs",
            "inboxSignatureDurationMs",
            "inboxReadDurationMs",
            "nonEmptyInboxCount",
            "wakeableMessageCount",
        ):
            summary[field] = max(0, int(scan.get(field) or 0))
        scan_error_type_counts = scan.get("errorTypeCounts")
        if isinstance(scan_error_type_counts, dict):
            for error_type, count in scan_error_type_counts.items():
                normalized_error_type = str(error_type or "").strip()
                if not normalized_error_type:
                    continue
                if len(summary["errorTypeCounts"]) < 8 or normalized_error_type in summary["errorTypeCounts"]:
                    summary["errorTypeCounts"][normalized_error_type] = (
                        int(summary["errorTypeCounts"].get(normalized_error_type) or 0)
                        + max(0, int(count or 0))
                    )
        summary["errorCount"] += max(0, int(scan.get("errorCount") or 0))
        for message in list(scan.get("messages") or []):
            if not isinstance(message, dict):
                continue
            try:
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
        summary["agentScanDurationMs"] = s._elapsed_ms(agent_scan_started_at)
    except Exception as exc:
        summary["errorCount"] += 1
        summary["errorTypeCounts"][type(exc).__name__] = 1
        if repair_started_at is not None and not summary["repairDurationMs"]:
            summary["repairDurationMs"] = s._elapsed_ms(repair_started_at)
        if agent_scan_started_at is not None and not summary["agentScanDurationMs"]:
            summary["agentScanDurationMs"] = s._elapsed_ms(agent_scan_started_at)
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
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
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
        s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
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
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
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
            s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
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


def _conversation_row_id(raw: dict[str, Any]) -> str:
    return str(raw.get("conversation_id") or raw.get("conversationId") or raw.get("id") or "").strip()


def _conversation_row_updated_at(raw: dict[str, Any]) -> str:
    return str(raw.get("updated_at") or raw.get("updatedAt") or "").strip()


def _delete_session_control_phase(session_id: str, conversation: dict[str, Any]) -> str:
    """Return running/stopping/queued without replaying turn journals."""
    s = _service()
    if s._is_session_stop_requested(session_id):
        return "stopping"
    last_status = str(
        conversation.get("last_turn_status") or conversation.get("lastTurnStatus") or ""
    ).strip().lower()
    if s._is_session_running(session_id):
        if last_status == "queued":
            return "queued"
        return "running"
    return last_status or "ready"


def _next_active_session_id_from_remaining(
    remaining: list[dict[str, Any]],
    *,
    current_active_id: str,
    deleted_session_id: str,
) -> str:
    s = _service()
    remaining_ids = [
        session_id
        for session_id in (_conversation_row_id(item) for item in remaining)
        if session_id
    ]
    normalized_active = str(current_active_id or "").strip()
    if (
        normalized_active
        and normalized_active != deleted_session_id
        and normalized_active in remaining_ids
    ):
        return normalized_active
    dated = [item for item in remaining if _conversation_row_id(item)]
    if not dated:
        return ""
    latest = max(
        dated,
        key=lambda item: s._timestamp_sort_key(_conversation_row_updated_at(item)),
    )
    return _conversation_row_id(latest)


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

    if not s._session_has_openable_body(conversation_id):
        s._retire_unopenable_directory_session(
            conversation_id,
            source="s.delete_chat_session",
        )
        if (
            s._session_workspace_dir_if_present(conversation_id) is not None
            and not s._is_session_workspace_intentionally_deleted(conversation_id)
        ):
            s._mark_session_workspace_intentionally_deleted(
                conversation_id,
                reason="deleted",
            )
        s._record_session_delete_event(
            "already_deleted",
            session_id=conversation_id,
            outcome="already_deleted",
            fields={
                "phase": "deleted",
                "agentId": "",
                "messageCount": 0,
            },
        )
        return {
            "nextActiveSessionId": str(s.load_active_conversation_id(s.PROJECT_ROOT) or "").strip(),
            "replacementDirectSessionId": "",
        }

    next_active_id = ""
    replacement_snapshot: dict[str, Any] | None = None
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
            # Idempotent delete: a session already marked intentionally deleted
            # (tombstone present) is treated as deleted success, not a 404.
            if s._is_session_workspace_intentionally_deleted(conversation_id):
                s._record_session_delete_event(
                    "already_deleted",
                    session_id=conversation_id,
                    outcome="already_deleted",
                    fields={
                        "phase": "deleted",
                        "agentId": "",
                        "messageCount": 0,
                    },
                )
                return {
                    "nextActiveSessionId": str(payload.get("active_conversation_id") or "").strip(),
                    "replacementDirectSessionId": "",
                }
            raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
        s._ensure_session_mutable(
            conversation_id,
            conversation=target_conversation,
        )
        s._ensure_conversation_workspace_metadata(target_conversation)
        target_agent_id = str(target_conversation.get("agent_id") or target_conversation.get("agentId") or "").strip()
        target_agent = s.get_agent(target_agent_id, include_archived=False) if target_agent_id else None
        target_agent_direct_session_id = str((target_agent or {}).get("directSessionId") or "").strip()

        # Keep this critical section off the journal replay path. The live
        # delete stall was resolve_target scanning turn_journal.jsonl (and
        # then normalizing every remaining conversation) while holding
        # _CHAT_STATE_LOCK, which blocked sibling GET detail / select.
        target_phase = _delete_session_control_phase(conversation_id, target_conversation)
        raw_messages = target_conversation.get("messages")
        target_message_count = len(raw_messages) if isinstance(raw_messages, list) else 0
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
        next_active_id = _next_active_session_id_from_remaining(
            remaining,
            current_active_id=current_active_id,
            deleted_session_id=conversation_id,
        )
        if not next_active_id:
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
            replacement_snapshot = dict(replacement_conversation)

        now = s._now_timestamp()
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["active_conversation_id"] = next_active_id
        payload["updated_at"] = now
        payload["conversations"] = remaining
        try:
            timed(
                "save_state_and_archive",
                lambda: s.save_chat_state(
                    s.PROJECT_ROOT,
                    payload,
                    archive_session_id=conversation_id,
                ),
            )
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

    from . import directory_bridge

    timings["directory_archive_dispatch"] = 0
    s._record_session_delete_event(
        "directory_archived",
        session_id=conversation_id,
        outcome="archived",
        fields={
            "durationMs": timings.get("save_state_and_archive", 0),
            "transactional": True,
        },
    )
    if replacement_snapshot is not None:
        directory_bridge.sync_conversation_record(replacement_snapshot)
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
    # Block workspace auto-recovery (llm-options / materialize) from resurrecting
    # intentionally deleted sessions after clear/reset/delete.
    tombstone_written = bool(
        s._mark_session_workspace_intentionally_deleted(
            conversation_id,
            reason="chat_session_deleted",
            agent_id=target_agent_id,
        )
    )
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
            "sessionDeletedTombstone": tombstone_written,
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
        restored_rows = [
            dict(raw)
            for raw in conversations
            if isinstance(raw, dict)
            and str(raw.get("conversation_id") or "").strip() in session_ids
        ]
        removed_replacement_id = replacement_id
    from . import directory_bridge

    directory_bridge.sync_conversation_records(restored_rows)
    if removed_replacement_id:
        directory_bridge.archive_directory_session_safe(removed_replacement_id)
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
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
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
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
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
    for message in messages:
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
