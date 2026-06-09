"""Bulk Agent delete/archive orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .agent_directory_service import (
    AgentDirectoryError,
    AgentNotFoundError,
    archive_agent_instance,
    ensure_agent_archive_allowed,
    ensure_agent_purge_allowed,
    ensure_agent_purge_workspace_deletable,
    purge_archived_agent_instance,
)
from .agent_mode_binding_service import remove_agents_from_mode_bindings
from .chat_room_service import remove_agents_from_chat_rooms
from .runtime_scene_service import record_runtime_scene_event
from .team_service import remove_agents_from_teams
from . import session_service


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _dedupe_agent_ids(agent_ids: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in list(agent_ids or []):
        agent_id = str(item or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        deduped.append(agent_id)
    return deduped


def _timed(timings: dict[str, float], stage: str, callback: Callable[[], Any]) -> Any:
    started_at = perf_counter()
    try:
        return callback()
    finally:
        elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
        timings[stage] = round(float(timings.get(stage) or 0.0) + elapsed_ms, 3)


def _skip_item(agent_id: str, reason: str, message: str) -> dict[str, str]:
    return {"agentId": agent_id, "reason": reason, "message": message}


def _failed_item(agent_id: str, reason: str, message: str) -> dict[str, str]:
    return {"agentId": agent_id, "reason": reason, "message": message}


def _purge_skip_reason(error: Exception) -> str:
    message = str(error)
    if isinstance(error, AgentNotFoundError):
        return "not_found"
    if "Only archived Agents can be permanently deleted" in message:
        return "not_archived"
    if "Protected core Agent cannot be purged" in message:
        return "protected"
    return "invalid"


def _archive_skip_reason(error: Exception) -> str:
    message = str(error)
    if isinstance(error, AgentNotFoundError):
        return "not_found"
    if "Protected core Agent cannot be archived" in message:
        return "protected"
    return "invalid"


def _status(success_count: int, skipped_count: int, failed_count: int) -> str:
    if failed_count:
        return "partial_failed" if success_count or skipped_count else "failed"
    return "completed"


def _summary(requested_count: int, success: list[dict[str, Any]], skipped: list[dict[str, Any]], failed: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "requestedCount": requested_count,
        "successCount": len(success),
        "skippedCount": len(skipped),
        "failedCount": len(failed),
    }


def _public_direct_session_cleanup(cleanup: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(cleanup or {}).items()
        if key != "restoreToken"
    }


def bulk_archive_agents(agent_ids: list[str] | None) -> dict[str, Any]:
    """Archive many Agents while scanning shared references once."""

    requested_agent_ids = _dedupe_agent_ids(agent_ids)
    timings: dict[str, float] = {}
    started_at = perf_counter()
    success: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    archive_candidates: list[dict[str, Any]] = []
    for agent_id in requested_agent_ids:
        try:
            agent = _timed(timings, "ensure_archive_allowed", lambda agent_id=agent_id: ensure_agent_archive_allowed(agent_id))
        except (AgentDirectoryError, AgentNotFoundError) as exc:
            skipped.append(_skip_item(agent_id, _archive_skip_reason(exc), str(exc)))
            continue
        if str(agent.get("status") or "active").strip() == "archived":
            skipped.append(_skip_item(agent_id, "already_archived", "Agent is already archived."))
            continue
        archive_candidates.append(agent)

    candidate_ids = [str(agent.get("agentId") or "").strip() for agent in archive_candidates if str(agent.get("agentId") or "").strip()]
    team_cleanup = {"changedTeamIds": []}
    room_cleanup = {"changedRoomIds": []}
    mode_cleanup = {"repairWarnings": []}
    if candidate_ids:
        team_cleanup = _timed(timings, "remove_from_teams", lambda: remove_agents_from_teams(candidate_ids))
        room_cleanup = _timed(timings, "remove_from_chat_rooms", lambda: remove_agents_from_chat_rooms(candidate_ids, include_chat_rooms=False))
        mode_cleanup = _timed(
            timings,
            "remove_from_mode_bindings",
            lambda: remove_agents_from_mode_bindings(
                candidate_ids,
                agent_snapshots_by_agent_id={str(agent.get("agentId") or "").strip(): agent for agent in archive_candidates},
            ),
        )
        for agent_id in candidate_ids:
            try:
                archived = _timed(timings, "archive_agents", lambda agent_id=agent_id: archive_agent_instance(agent_id, repair_mode_bindings=False))
            except (AgentDirectoryError, AgentNotFoundError) as exc:
                failed.append(_failed_item(agent_id, _archive_skip_reason(exc), str(exc)))
                continue
            success.append(
                {
                    **archived,
                    "archiveSummary": {
                        "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                        "removedFromRoomIds": list((room_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "removedFromTeamIds": list((team_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "dataRetention": "archived_only",
                    },
                }
            )

    summary = _summary(len(requested_agent_ids), success, skipped, failed)
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    record_runtime_scene_event(
        "agent_directory",
        "delete",
        "agent.bulk_archive.completed",
        outcome="failed" if summary["failedCount"] else "succeeded",
        fields={
            **summary,
            "durationMs": duration_ms,
            "timingsMs": timings,
            "removedFromTeamCount": len(team_cleanup.get("changedTeamIds") or []),
            "removedFromRoomCount": len(room_cleanup.get("changedRoomIds") or []),
            "modeBindingRepairWarningCount": len(mode_cleanup.get("repairWarnings") or []),
        },
    )
    return {
        "status": _status(summary["successCount"], summary["skippedCount"], summary["failedCount"]),
        "requestedAgentIds": requested_agent_ids,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "summary": summary,
        "cleanupSummary": {
            "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
            "removedFromTeamIds": list(team_cleanup.get("changedTeamIds") or []),
            "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
            "dataRetention": "archived_only",
        },
        "timingsMs": timings,
        "durationMs": duration_ms,
    }


def bulk_purge_agents(agent_ids: list[str] | None) -> dict[str, Any]:
    """Permanently delete many archived Agents while scanning shared references once."""

    requested_agent_ids = _dedupe_agent_ids(agent_ids)
    timings: dict[str, float] = {}
    started_at = perf_counter()
    success: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    purge_candidates: list[dict[str, Any]] = []
    for agent_id in requested_agent_ids:
        try:
            agent = _timed(timings, "ensure_purge_allowed", lambda agent_id=agent_id: ensure_agent_purge_allowed(agent_id))
            _timed(timings, "ensure_workspace_deletable", lambda agent=agent: ensure_agent_purge_workspace_deletable(agent))
        except AgentNotFoundError as exc:
            failed.append(_failed_item(agent_id, "not_found", str(exc)))
            continue
        except AgentDirectoryError as exc:
            skipped.append(_skip_item(agent_id, _purge_skip_reason(exc), str(exc)))
            continue
        purge_candidates.append(agent)

    candidate_ids = [str(agent.get("agentId") or "").strip() for agent in purge_candidates if str(agent.get("agentId") or "").strip()]
    snapshots_by_agent_id = {str(agent.get("agentId") or "").strip(): agent for agent in purge_candidates}
    direct_session_ids_by_agent_id = {
        agent_id: str(snapshots_by_agent_id.get(agent_id, {}).get("directSessionId") or "").strip()
        for agent_id in candidate_ids
    }
    team_cleanup = {"changedTeamIds": []}
    room_cleanup = {"changedRoomIds": []}
    mode_cleanup = {"repairWarnings": []}
    direct_session_cleanups: list[dict[str, Any]] = []
    direct_session_cleanup_by_agent_id: dict[str, dict[str, Any]] = {}
    direct_session_restore_tokens_by_agent_id: dict[str, dict[str, Any]] = {}
    purge_ready_agent_ids: list[str] = []
    if candidate_ids:
        for agent_id in candidate_ids:
            snapshot = snapshots_by_agent_id.get(agent_id, {})
            direct_session_id = str(snapshot.get("directSessionId") or "").strip()
            direct_session_cleanup = (
                _timed(
                    timings,
                    "mark_direct_session_deleted_agent",
                    lambda direct_session_id=direct_session_id, agent_id=agent_id, snapshot=snapshot: session_service.mark_direct_session_agent_deleted(
                        direct_session_id,
                        agent_id=agent_id,
                        agent_display_name=str(snapshot.get("displayName") or "").strip(),
                        previous_status=str(snapshot.get("status") or "active").strip() or "active",
                        include_restore_token=True,
                    ),
                )
                if direct_session_id
                else {"changed": False, "sessionId": "", "agentId": agent_id, "reason": "no_direct_session"}
            )
            public_direct_session_cleanup = _public_direct_session_cleanup(direct_session_cleanup)
            direct_session_cleanup_by_agent_id[agent_id] = public_direct_session_cleanup
            direct_session_cleanups.append(public_direct_session_cleanup)
            restore_token = direct_session_cleanup.get("restoreToken")
            if isinstance(restore_token, dict):
                direct_session_restore_tokens_by_agent_id[agent_id] = restore_token
            if str(direct_session_cleanup.get("reason") or "").strip() == "tombstone_failed":
                failed.append(
                    _failed_item(
                        agent_id,
                        "tombstone_failed",
                        "Agent direct-session tombstone failed before permanent delete; Agent references and workspace were not deleted.",
                    )
                )
                continue
            purge_ready_agent_ids.append(agent_id)

    if purge_ready_agent_ids:
        try:
            team_cleanup = _timed(timings, "remove_from_teams", lambda: remove_agents_from_teams(purge_ready_agent_ids))
            room_cleanup = _timed(
                timings,
                "remove_from_chat_rooms",
                lambda: remove_agents_from_chat_rooms(
                    purge_ready_agent_ids,
                    allow_empty_rooms=True,
                    direct_session_ids_by_agent_id=direct_session_ids_by_agent_id,
                    include_chat_rooms=False,
                ),
            )
            mode_cleanup = _timed(
                timings,
                "remove_from_mode_bindings",
                lambda: remove_agents_from_mode_bindings(purge_ready_agent_ids, agent_snapshots_by_agent_id=snapshots_by_agent_id),
            )
        except Exception:
            for agent_id in purge_ready_agent_ids:
                restore_token = direct_session_restore_tokens_by_agent_id.get(agent_id)
                if restore_token:
                    _timed(
                        timings,
                        "rollback_direct_session_deleted_agent",
                        lambda restore_token=restore_token: session_service.restore_direct_session_agent_deleted_tombstone(restore_token),
                    )
            raise
        for agent_id in purge_ready_agent_ids:
            direct_session_cleanup = direct_session_cleanup_by_agent_id.get(
                agent_id,
                {"changed": False, "sessionId": "", "agentId": agent_id, "reason": "no_direct_session"},
            )
            try:
                purge = _timed(timings, "purge_agents", lambda agent_id=agent_id: purge_archived_agent_instance(agent_id))
            except (AgentDirectoryError, AgentNotFoundError) as exc:
                restore_token = direct_session_restore_tokens_by_agent_id.get(agent_id)
                if restore_token:
                    _timed(
                        timings,
                        "rollback_direct_session_deleted_agent",
                        lambda restore_token=restore_token: session_service.restore_direct_session_agent_deleted_tombstone(restore_token),
                    )
                failed.append(_failed_item(agent_id, _purge_skip_reason(exc), str(exc)))
                continue
            success.append(
                {
                    **purge,
                    "purgeSummary": {
                        "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                        "removedFromRoomIds": list((room_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "removedFromTeamIds": list((team_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "directSession": direct_session_cleanup,
                        "dataRetention": "purged",
                    },
                }
            )

    summary = _summary(len(requested_agent_ids), success, skipped, failed)
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    record_runtime_scene_event(
        "agent_directory",
        "delete",
        "agent.bulk_purge.completed",
        outcome="failed" if summary["failedCount"] else "succeeded",
        fields={
            **summary,
            "durationMs": duration_ms,
            "timingsMs": timings,
            "removedFromTeamCount": len(team_cleanup.get("changedTeamIds") or []),
            "removedFromRoomCount": len(room_cleanup.get("changedRoomIds") or []),
            "modeBindingRepairWarningCount": len(mode_cleanup.get("repairWarnings") or []),
            "directSessionTombstoneCount": len([item for item in direct_session_cleanups if item.get("changed")]),
        },
    )
    return {
        "status": _status(summary["successCount"], summary["skippedCount"], summary["failedCount"]),
        "requestedAgentIds": requested_agent_ids,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "summary": summary,
        "cleanupSummary": {
            "removedFromRoomIds": list(room_cleanup.get("changedRoomIds") or []),
            "removedFromTeamIds": list(team_cleanup.get("changedTeamIds") or []),
            "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
            "directSessions": [_public_direct_session_cleanup(item) for item in direct_session_cleanups],
            "dataRetention": "purged",
        },
        "timingsMs": timings,
        "durationMs": duration_ms,
    }
