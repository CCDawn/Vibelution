"""Team runtime-scene logging helpers.

Claim scope: team event emission, detail-load telemetry, membership/archive
conflict logs, and system-team sync failure logs.
Late-binds ``team_service`` for detail-log state and thresholds.
"""

from __future__ import annotations

from typing import Any

from core.logging.logger import debug as _debug_logger


def _service():
    from core.web.services import team_service

    return team_service


def _record_team_event(event_code: str, team: dict[str, Any], *, fields: dict[str, Any] | None = None) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team",
            event_code,
            message=f"Team {team.get('teamId')} {event_code}",
            outcome="succeeded",
            fields={
                "teamId": team.get("teamId"),
                "teamName": team.get("name"),
                "status": team.get("status"),
                "teamKind": team.get("teamKind"),
                "teamCategory": team.get("teamCategory"),
                "teamSource": team.get("teamSource"),
                "teamTemplateId": team.get("teamTemplateId"),
                **(fields or {}),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to emit team loaded event. error={exc}")


def _team_detail_log_fields(team: dict[str, Any], started_at: float) -> dict[str, Any]:
    s = _service()
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    return {
        "teamId": str(team.get("teamId") or "").strip(),
        "teamName": str(team.get("name") or "").strip(),
        "teamKind": str(team.get("teamKind") or "").strip(),
        "teamCategory": str(team.get("teamCategory") or "").strip(),
        "teamSource": str(team.get("teamSource") or "").strip(),
        "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
        "linkedChatRoomId": str(team.get("linkedChatRoomId") or "").strip(),
        "memberCount": len(list(team.get("members") or [])),
        "canvasNodeCount": len(list(canvas.get("nodes") or [])),
        "canvasEdgeCount": len(list(canvas.get("edges") or [])),
        "elapsedMs": s._elapsed_ms(started_at),
    }


def _team_detail_log_signature(fields: dict[str, Any]) -> tuple[Any, ...]:
    return (
        fields.get("teamKind"),
        fields.get("teamSource"),
        fields.get("teamTemplateId"),
        fields.get("linkedChatRoomId"),
        fields.get("memberCount"),
        fields.get("canvasNodeCount"),
        fields.get("canvasEdgeCount"),
    )


def _emit_team_detail_loaded(fields: dict[str, Any], *, reason: str) -> None:
    s = _service()
    s.record_runtime_scene_event(
        "team_service",
        "team_detail",
        "team.detail.loaded",
        message="Team detail loaded.",
        outcome="observed",
        fields={**fields, "logReason": reason},
    )


def _emit_team_detail_rollup(team_id: str, state: dict[str, Any], *, now: float) -> None:
    s = _service()
    repeat_count = int(state.get("repeatCount") or 0)
    if repeat_count <= 0:
        return
    fields = dict(state.get("lastFields") or {})
    s.record_runtime_scene_event(
        "team_service",
        "team_detail",
        "team.detail.loaded_rollup",
        message="Repeated team detail loads suppressed.",
        outcome="observed",
        fields={
            "teamId": team_id,
            "teamName": str(fields.get("teamName") or ""),
            "teamKind": str(fields.get("teamKind") or ""),
            "teamSource": str(fields.get("teamSource") or ""),
            "linkedChatRoomId": str(fields.get("linkedChatRoomId") or ""),
            "memberCount": fields.get("memberCount", 0),
            "canvasNodeCount": fields.get("canvasNodeCount", 0),
            "canvasEdgeCount": fields.get("canvasEdgeCount", 0),
            "repeatCount": repeat_count,
            "windowSeconds": round(max(0.0, now - float(state.get("windowStartedAt") or now)), 3),
            "maxElapsedMs": state.get("maxElapsedMs", 0),
            "lastElapsedMs": fields.get("elapsedMs", 0),
            "rollupReason": "same_signature_repeated",
        },
    )
    state["repeatCount"] = 0
    state["windowStartedAt"] = now
    state["lastRollupAt"] = now


def _record_team_detail_loaded(team: dict[str, Any], started_at: float) -> None:
    s = _service()
    try:
        fields = s._team_detail_log_fields(team, started_at)
        team_id = str(fields.get("teamId") or "").strip()
        if not team_id:
            return
        now = s._perf_counter()
        signature = s._team_detail_log_signature(fields)
        elapsed_ms = int(fields.get("elapsedMs") or 0)
        with s._TEAM_DETAIL_LOG_LOCK:
            state = s._TEAM_DETAIL_LOG_STATE.get(team_id)
            if state is None:
                s._TEAM_DETAIL_LOG_STATE[team_id] = {
                    "signature": signature,
                    "repeatCount": 0,
                    "windowStartedAt": now,
                    "lastRollupAt": 0.0,
                    "maxElapsedMs": elapsed_ms,
                    "lastFields": fields,
                }
                s._emit_team_detail_loaded(fields, reason="initial")
                return

            previous_signature = state.get("signature")
            if previous_signature != signature:
                s._emit_team_detail_rollup(team_id, state, now=now)
                state.update(
                    {
                        "signature": signature,
                        "repeatCount": 0,
                        "windowStartedAt": now,
                        "maxElapsedMs": elapsed_ms,
                        "lastFields": fields,
                    }
                )
                s._emit_team_detail_loaded(fields, reason="changed")
                return

            state["lastFields"] = fields
            state["maxElapsedMs"] = max(int(state.get("maxElapsedMs") or 0), elapsed_ms)
            if elapsed_ms >= s.TEAM_DETAIL_LOG_SLOW_THRESHOLD_MS:
                s._emit_team_detail_rollup(team_id, state, now=now)
                state["maxElapsedMs"] = elapsed_ms
                s._emit_team_detail_loaded(fields, reason="slow")
                return

            state["repeatCount"] = int(state.get("repeatCount") or 0) + 1
            if (
                int(state.get("repeatCount") or 0) >= s.TEAM_DETAIL_LOG_ROLLUP_REPEAT_THRESHOLD
            ):
                s._emit_team_detail_rollup(team_id, state, now=now)
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team detail loaded telemetry. error={exc}")


def _record_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any]) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team",
            "team.membership_conflict_rejected",
            message="Team member assignment rejected because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team membership conflict for team={team_id}. error={exc}")


def _record_team_archive_rejected(
    team: dict[str, Any],
    *,
    reason: str,
    agent_id: str = "",
    error: Exception | None = None,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team",
            "team.archive_rejected",
            message="Team archive rejected before cascading Agent archive.",
            outcome="blocked",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "reason": str(reason or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "errorType": type(error).__name__ if error else "",
                "message": str(error) if error else "",
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record team archive rejected for team={team.get('teamId')}. error={exc}")


def _record_archived_team_member_cascade_repaired(
    team: dict[str, Any],
    archived_agent_ids: list[str],
    *,
    reason: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team_repair",
            "team.archived_agent_cascade_repaired",
            message="Archived Team had active member Agents; cascading archive repair applied.",
            outcome="repaired",
            fields={
                "teamId": str(team.get("teamId") or "").strip(),
                "teamName": str(team.get("name") or "").strip(),
                "teamKind": str(team.get("teamKind") or s._infer_team_kind(team)).strip(),
                "teamCategory": str(team.get("teamCategory") or "").strip(),
                "teamSource": str(team.get("teamSource") or "").strip(),
                "teamTemplateId": str(team.get("teamTemplateId") or "").strip(),
                "archivedAgentIds": archived_agent_ids,
                "archivedAgentCount": len(archived_agent_ids),
                "reason": str(reason or "").strip(),
            },
        )
    except Exception as exc:
        _debug_logger.warning(
            f"Failed to record archived team member cascade repaired for team={team.get('teamId')}. error={exc}"
        )


def _record_system_team_membership_conflict(team_id: str, agent_id: str, conflict: dict[str, Any], *, source: str) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "team_service",
            "team",
            "team.system_membership_conflict",
            message="System Team member was not synced because the Agent already belongs to another active Team",
            outcome="blocked",
            fields={
                "teamId": team_id,
                "agentId": agent_id,
                "source": source,
                "conflictTeamId": conflict.get("teamId"),
                "conflictTeamName": conflict.get("name"),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record system team membership conflict for team={team_id}. error={exc}")


def _record_system_team_sync_failed(source: str, exc: Exception) -> None:
    s = _service()
    try:
        normalized_source = str(source or "").strip()
        event_code = "team.ai_search_system_sync_failed" if normalized_source == "ai_search" else "team.system_evolution_sync_failed"
        message = "AI search system Team sync failed" if normalized_source == "ai_search" else "System evolution Team sync failed"
        s.record_runtime_scene_event(
            "team_service",
            "team",
            event_code,
            message=message,
            level="warning",
            outcome="failed",
            fields={
                "source": normalized_source,
                "errorType": type(exc).__name__,
                "message": str(exc),
            },
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record system team sync failure source={source}. error={exc}")
