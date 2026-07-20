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
    reactivate_agent_instance,
)
from .agent_mode_binding_service import (
    get_mode_bindings_payload,
    remove_agents_from_mode_bindings,
    restore_removed_agents_to_mode_bindings,
)
from .chat_room_service import remove_agents_from_chat_rooms, restore_removed_agents_to_chat_rooms
from .runtime_scene_service import record_runtime_scene_event
from .team_service import remove_agents_from_teams, restore_removed_agents_to_teams
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


def _public_agent_session_cleanup(cleanup: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(cleanup or {}).items()
        if key not in {"restoreToken", "stagingRoot", "stagingRoots"}
    }


def _run_best_effort_compensations(
    timings: dict[str, float],
    compensations: list[tuple[str, Callable[[], Any]]],
) -> list[str]:
    failures: list[str] = []
    for stage, callback in compensations:
        try:
            _timed(timings, stage, callback)
        except Exception as rollback_error:
            failures.append(f"{stage}:{type(rollback_error).__name__}")
    return failures


def _prepare_bulk_archive_references(
    candidate_ids: list[str],
    *,
    snapshots_by_agent_id: dict[str, dict[str, Any]],
    timings: dict[str, float],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Remove archive references while compensating every completed stage on failure."""

    mode_restore_token = _timed(timings, "snapshot_mode_bindings", get_mode_bindings_payload)
    team_cleanup: dict[str, Any] = {}
    room_cleanup: dict[str, Any] = {}
    try:
        team_cleanup = _timed(
            timings,
            "remove_from_teams",
            lambda: remove_agents_from_teams(candidate_ids, include_restore_token=True),
        )
        room_cleanup = _timed(
            timings,
            "remove_from_chat_rooms",
            lambda: remove_agents_from_chat_rooms(
                candidate_ids,
                include_chat_rooms=False,
                include_restore_token=True,
            ),
        )
        mode_cleanup = _timed(
            timings,
            "remove_from_mode_bindings",
            lambda: remove_agents_from_mode_bindings(
                candidate_ids,
                agent_snapshots_by_agent_id=snapshots_by_agent_id,
            ),
        )
    except Exception as exc:
        rollback_failures: list[str] = []
        for stage, callback in (
            (
                "rollback_mode_bindings",
                lambda: restore_removed_agents_to_mode_bindings(mode_restore_token),
            ),
            (
                "rollback_chat_rooms",
                lambda: restore_removed_agents_to_chat_rooms(room_cleanup.get("restoreToken")),
            ),
            (
                "rollback_teams",
                lambda: restore_removed_agents_to_teams(team_cleanup.get("restoreToken")),
            ),
        ):
            try:
                _timed(timings, stage, callback)
            except Exception as rollback_error:
                rollback_failures.append(f"{stage}:{type(rollback_error).__name__}")
        if rollback_failures:
            raise AgentDirectoryError(
                "Bulk archive reference cleanup failed and compensation was incomplete: "
                + ", ".join(rollback_failures)
            ) from exc
        raise
    return mode_restore_token, team_cleanup, room_cleanup, mode_cleanup


def bulk_archive_agents(agent_ids: list[str] | None) -> dict[str, Any]:
    """Archive many Agents with per-Agent compensation on write failure."""

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
        archive_candidates.append(agent)

    candidate_ids = [str(agent.get("agentId") or "").strip() for agent in archive_candidates if str(agent.get("agentId") or "").strip()]
    team_cleanup = {"changedTeamIds": []}
    room_cleanup = {"changedRoomIds": []}
    mode_cleanup = {"repairWarnings": []}
    if candidate_ids:
        snapshots_by_agent_id = {str(agent.get("agentId") or "").strip(): agent for agent in archive_candidates}
        mode_restore_token, team_cleanup, room_cleanup, mode_cleanup = _prepare_bulk_archive_references(
            candidate_ids,
            snapshots_by_agent_id=snapshots_by_agent_id,
            timings=timings,
        )
        archived_by_agent_id: dict[str, dict[str, Any]] = {}
        session_archive_by_agent_id: dict[str, dict[str, Any]] = {}
        session_archive_restore_tokens_by_agent_id: dict[str, dict[str, Any]] = {}
        newly_archived_agent_ids: set[str] = set()
        archive_failure: tuple[str, Exception] | None = None
        for agent_id in candidate_ids:
            session_archive: dict[str, Any] = {}
            try:
                snapshot = snapshots_by_agent_id.get(agent_id, {})
                session_archive = _timed(
                    timings,
                    "archive_agent_sessions",
                    lambda agent_id=agent_id, snapshot=snapshot: session_service.archive_agent_sessions(
                        agent_id,
                        direct_session_id=str(snapshot.get("directSessionId") or "").strip(),
                        include_restore_token=True,
                    ),
                )
                session_archive_by_agent_id[agent_id] = _public_agent_session_cleanup(session_archive)
                restore_token = session_archive.get("restoreToken")
                if isinstance(restore_token, dict):
                    session_archive_restore_tokens_by_agent_id[agent_id] = restore_token
                archived_by_agent_id[agent_id] = _timed(
                    timings,
                    "archive_agents",
                    lambda agent_id=agent_id: archive_agent_instance(agent_id, repair_mode_bindings=False),
                )
                if str(snapshot.get("status") or "active").strip() != "archived":
                    newly_archived_agent_ids.add(agent_id)
            except Exception as exc:
                restore_token = session_archive.get("restoreToken")
                if isinstance(restore_token, dict):
                    rollback_failures = _run_best_effort_compensations(
                        timings,
                        [
                            (
                                "rollback_agent_sessions",
                                lambda restore_token=restore_token: session_service.restore_agent_sessions_archive(
                                    restore_token
                                ),
                            )
                        ],
                    )
                    if rollback_failures:
                        exc.add_note(
                            "Bulk archive compensation incomplete: "
                            + ", ".join(rollback_failures)
                        )
                archive_failure = (agent_id, exc)
                break
        if archive_failure is not None:
            failed_agent_id, archive_error = archive_failure
            compensations: list[tuple[str, Callable[[], Any]]] = []
            for archived_agent_id in reversed(list(archived_by_agent_id)):
                if archived_agent_id in newly_archived_agent_ids:
                    compensations.append(
                        (
                            "rollback_archived_agents",
                            lambda archived_agent_id=archived_agent_id: reactivate_agent_instance(
                                archived_agent_id,
                                reason="bulk_archive_rollback",
                            ),
                        )
                    )
                restore_token = session_archive_restore_tokens_by_agent_id.get(archived_agent_id)
                if restore_token:
                    compensations.append(
                        (
                            "rollback_agent_sessions",
                            lambda restore_token=restore_token: session_service.restore_agent_sessions_archive(
                                restore_token
                            ),
                        )
                    )
            compensations.extend(
                [
                    (
                        "rollback_mode_bindings",
                        lambda: restore_removed_agents_to_mode_bindings(mode_restore_token),
                    ),
                    (
                        "rollback_chat_rooms",
                        lambda: restore_removed_agents_to_chat_rooms(
                            room_cleanup.get("restoreToken")
                        ),
                    ),
                    (
                        "rollback_teams",
                        lambda: restore_removed_agents_to_teams(
                            team_cleanup.get("restoreToken")
                        ),
                    ),
                ]
            )
            rollback_failures = _run_best_effort_compensations(
                timings,
                compensations,
            )
            if rollback_failures:
                archive_error.add_note(
                    "Bulk archive compensation incomplete: "
                    + ", ".join(rollback_failures)
                )
            for agent_id in candidate_ids:
                if agent_id == failed_agent_id:
                    failed.append(_failed_item(agent_id, _archive_skip_reason(archive_error), str(archive_error)))
                else:
                    failed.append(_failed_item(agent_id, "batch_rolled_back", "Bulk archive was rolled back because another Agent could not be archived."))
        else:
            for agent_id in candidate_ids:
                archived = archived_by_agent_id[agent_id]
                success.append(
                    {
                        **archived,
                        "archiveSummary": {
                            "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                            "removedFromRoomIds": list((room_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                            "removedFromTeamIds": list((team_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                            "sessions": session_archive_by_agent_id.get(agent_id, {}),
                            "dataRetention": "sealed",
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
            "archivedSessionCount": sum(
                int(item.get("archivedCount") or 0)
                for item in session_archive_by_agent_id.values()
            ) if candidate_ids else 0,
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
            "dataRetention": "sealed",
        },
        "timingsMs": timings,
        "durationMs": duration_ms,
    }


def bulk_purge_agents(agent_ids: list[str] | None) -> dict[str, Any]:
    """Permanently delete archived Agents with per-Agent transactional compensation."""

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
    session_purges: list[dict[str, Any]] = []
    session_purge_by_agent_id: dict[str, dict[str, Any]] = {}
    session_purge_restore_tokens_by_agent_id: dict[str, dict[str, Any]] = {}
    purge_ready_agent_ids: list[str] = []
    if candidate_ids:
        for agent_id in candidate_ids:
            snapshot = snapshots_by_agent_id.get(agent_id, {})
            direct_session_id = str(snapshot.get("directSessionId") or "").strip()
            try:
                session_purge = _timed(
                    timings,
                    "stage_agent_session_purge",
                    lambda direct_session_id=direct_session_id, agent_id=agent_id: session_service.stage_agent_session_purge(
                        agent_id,
                        direct_session_id=direct_session_id,
                    ),
                )
            except Exception as exc:
                failed.append(
                    _failed_item(
                        agent_id,
                        "session_purge_stage_failed",
                        f"Agent session purge staging failed before permanent delete: {type(exc).__name__}",
                    )
                )
                continue
            public_session_purge = _public_agent_session_cleanup(session_purge)
            session_purge_by_agent_id[agent_id] = public_session_purge
            restore_token = session_purge.get("restoreToken")
            if isinstance(restore_token, dict):
                session_purge_restore_tokens_by_agent_id[agent_id] = restore_token
            purge_ready_agent_ids.append(agent_id)

    if purge_ready_agent_ids:
        mode_restore_token = _timed(
            timings,
            "snapshot_mode_bindings",
            get_mode_bindings_payload,
        )
        try:
            team_cleanup = _timed(
                timings,
                "remove_from_teams",
                lambda: remove_agents_from_teams(
                    purge_ready_agent_ids,
                    include_restore_token=True,
                ),
            )
            room_cleanup = _timed(
                timings,
                "remove_from_chat_rooms",
                lambda: remove_agents_from_chat_rooms(
                    purge_ready_agent_ids,
                    allow_empty_rooms=True,
                    direct_session_ids_by_agent_id=direct_session_ids_by_agent_id,
                    include_chat_rooms=False,
                    include_restore_token=True,
                ),
            )
            mode_cleanup = _timed(
                timings,
                "remove_from_mode_bindings",
                lambda: remove_agents_from_mode_bindings(
                    purge_ready_agent_ids,
                    agent_snapshots_by_agent_id=snapshots_by_agent_id,
                ),
            )
        except Exception as exc:
            compensations: list[tuple[str, Callable[[], Any]]] = []
            for ready_agent_id in purge_ready_agent_ids:
                restore_token = session_purge_restore_tokens_by_agent_id.get(
                    ready_agent_id
                )
                if restore_token:
                    compensations.append(
                        (
                            "rollback_agent_session_purge",
                            lambda restore_token=restore_token: session_service.restore_staged_agent_session_purge(
                                restore_token
                            ),
                        )
                    )
            compensations.extend(
                [
                    (
                        "rollback_mode_bindings",
                        lambda: restore_removed_agents_to_mode_bindings(
                            mode_restore_token
                        ),
                    ),
                    (
                        "rollback_chat_rooms",
                        lambda: restore_removed_agents_to_chat_rooms(
                            room_cleanup.get("restoreToken")
                        ),
                    ),
                    (
                        "rollback_teams",
                        lambda: restore_removed_agents_to_teams(
                            team_cleanup.get("restoreToken")
                        ),
                    ),
                ]
            )
            rollback_failures = _run_best_effort_compensations(
                timings,
                compensations,
            )
            if rollback_failures:
                exc.add_note(
                    "Bulk purge compensation incomplete: "
                    + ", ".join(rollback_failures)
                )
            raise

        successful_agent_ids: list[str] = []
        purge_failed_agent_ids: list[str] = []
        for agent_id in purge_ready_agent_ids:
            session_purge = session_purge_by_agent_id.get(agent_id, {})
            restore_token = session_purge_restore_tokens_by_agent_id.get(agent_id)
            try:
                purge = _timed(
                    timings,
                    "purge_agents",
                    lambda agent_id=agent_id: purge_archived_agent_instance(agent_id),
                )
            except Exception as exc:
                purge_failed_agent_ids.append(agent_id)
                rollback_failures: list[str] = []
                if restore_token:
                    rollback_failures = _run_best_effort_compensations(
                        timings,
                        [
                            (
                                "rollback_agent_session_purge",
                                lambda restore_token=restore_token: session_service.restore_staged_agent_session_purge(
                                    restore_token
                                ),
                            )
                        ],
                    )
                failure_message = str(exc)
                if rollback_failures:
                    failure_message += (
                        "; compensation incomplete: "
                        + ", ".join(rollback_failures)
                    )
                failed.append(
                    _failed_item(
                        agent_id,
                        _purge_skip_reason(exc),
                        failure_message,
                    )
                )
                continue
            successful_agent_ids.append(agent_id)
            committed_session_purge = _timed(
                timings,
                "commit_agent_session_purge",
                lambda restore_token=restore_token: session_service.commit_staged_agent_session_purge(
                    restore_token
                ),
            )
            public_session_purge = _public_agent_session_cleanup({
                **session_purge,
                **committed_session_purge,
            })
            session_purges.append(public_session_purge)
            success.append(
                {
                    **purge,
                    "purgeSummary": {
                        "modeBindingsRepaired": len(mode_cleanup.get("repairWarnings") or []),
                        "removedFromRoomIds": list((room_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "removedFromTeamIds": list((team_cleanup.get("removedByAgentId") or {}).get(agent_id) or []),
                        "sessions": public_session_purge,
                        "dataRetention": "purged",
                    },
                }
            )

        if purge_failed_agent_ids:
            reference_rollback_failures = _run_best_effort_compensations(
                timings,
                [
                    (
                        "rollback_mode_bindings",
                        lambda: restore_removed_agents_to_mode_bindings(
                            mode_restore_token
                        ),
                    ),
                    (
                        "rollback_chat_rooms",
                        lambda: restore_removed_agents_to_chat_rooms(
                            room_cleanup.get("restoreToken")
                        ),
                    ),
                    (
                        "rollback_teams",
                        lambda: restore_removed_agents_to_teams(
                            team_cleanup.get("restoreToken")
                        ),
                    ),
                ],
            )
            if successful_agent_ids:
                try:
                    team_cleanup = _timed(
                        timings,
                        "reconcile_successful_team_removals",
                        lambda: remove_agents_from_teams(successful_agent_ids),
                    )
                    room_cleanup = _timed(
                        timings,
                        "reconcile_successful_room_removals",
                        lambda: remove_agents_from_chat_rooms(
                            successful_agent_ids,
                            allow_empty_rooms=True,
                            direct_session_ids_by_agent_id={
                                agent_id: direct_session_ids_by_agent_id.get(
                                    agent_id,
                                    "",
                                )
                                for agent_id in successful_agent_ids
                            },
                            include_chat_rooms=False,
                            repair_participants=False,
                        ),
                    )
                    mode_cleanup = _timed(
                        timings,
                        "reconcile_successful_mode_removals",
                        lambda: remove_agents_from_mode_bindings(
                            successful_agent_ids,
                            agent_snapshots_by_agent_id=snapshots_by_agent_id,
                        ),
                    )
                except Exception as reconciliation_error:
                    reference_rollback_failures.append(
                        "reconcile_successful_references:"
                        + type(reconciliation_error).__name__
                    )
            else:
                team_cleanup = {"changedTeamIds": [], "removedByAgentId": {}}
                room_cleanup = {"changedRoomIds": [], "removedByAgentId": {}}
                mode_cleanup = {"repairWarnings": []}
            if reference_rollback_failures:
                detail = ", ".join(reference_rollback_failures)
                for item in failed:
                    if item.get("agentId") in purge_failed_agent_ids:
                        item["message"] = (
                            f"{item.get('message') or ''}; "
                            f"reference compensation incomplete: {detail}"
                        )

        for item in success:
            success_agent_id = str(item.get("agentId") or "").strip()
            purge_summary = item.get("purgeSummary")
            if not isinstance(purge_summary, dict):
                continue
            purge_summary["modeBindingsRepaired"] = len(
                mode_cleanup.get("repairWarnings") or []
            )
            purge_summary["removedFromRoomIds"] = list(
                (room_cleanup.get("removedByAgentId") or {}).get(
                    success_agent_id
                )
                or []
            )
            purge_summary["removedFromTeamIds"] = list(
                (team_cleanup.get("removedByAgentId") or {}).get(
                    success_agent_id
                )
                or []
            )

    summary = _summary(len(requested_agent_ids), success, skipped, failed)
    cleanup_pending_count = sum(
        1
        for item in success
        if bool(
            ((item.get("purgeSummary") or {}).get("sessions") or {}).get("cleanupPending")
        )
    )
    duration_ms = round((perf_counter() - started_at) * 1000, 3)
    record_runtime_scene_event(
        "agent_directory",
        "delete",
        "agent.bulk_purge.completed",
        level="warning" if summary["failedCount"] or cleanup_pending_count else "info",
        outcome=(
            "failed"
            if summary["failedCount"]
            else "partial"
            if cleanup_pending_count
            else "succeeded"
        ),
        fields={
            **summary,
            "durationMs": duration_ms,
            "timingsMs": timings,
            "removedFromTeamCount": len(team_cleanup.get("changedTeamIds") or []),
            "removedFromRoomCount": len(room_cleanup.get("changedRoomIds") or []),
            "modeBindingRepairWarningCount": len(mode_cleanup.get("repairWarnings") or []),
            "deletedSessionCount": sum(int(item.get("deletedCount") or 0) for item in session_purges),
            "cleanupPendingCount": cleanup_pending_count,
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
            "sessions": [_public_agent_session_cleanup(item) for item in session_purges],
            "dataRetention": "purged",
        },
        "timingsMs": timings,
        "durationMs": duration_ms,
    }
