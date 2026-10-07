"""Research organization team shell helpers.

Claim scope: ensure the locked research organization has a stable Team shell,
and keep the narrow chat-room link maintenance this legacy entrypoint provides.
Team.members is owned by the PATCH team aggregation entrypoint; the legacy
organization graph never materializes members into ``teams.json``.
Late-binds ``team_service`` for index locks, contracts, and chat-room link.
"""

from __future__ import annotations

from typing import Any

from core.logging import debug as _debug_logger


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import team_service

    return team_service


def ensure_research_team_from_organization(organization: dict[str, Any]) -> dict[str, Any]:
    """Ensure the locked research organization has a stable Team reference."""

    s = _service()
    team_id = "research-team"
    # ``research-team`` is also the durable Challenge Cup asset Team. Once it
    # exists, the legacy organization projection must not replace its canonical
    # membership or regenerate its Canvas from old state. Team.members facts
    # come only from the PATCH team aggregation entrypoint.
    with s._TEAM_LOCK:
        existing_state = s._load_index()
        existing_team = s._find_team(existing_state, team_id)
        if existing_team is not None:
            # Preserve the existing roster/Canvas while retaining the narrow
            # chat-room link maintenance this legacy entrypoint historically
            # provided. Chat-room projection reads Team.members and never
            # writes Agent configuration.
            s._ensure_team_chat_room_link(existing_team)
            existing_state["updatedAt"] = str(
                existing_team.get("updatedAt") or existing_state.get("updatedAt") or ""
            )
            s._save_index(existing_state)
    if existing_team is not None:
        return s.get_team(team_id)

    now = s.utc_now_iso()
    with s._TEAM_LOCK:
        state = s._load_index()
        if s._repair_index_state(state):
            state["updatedAt"] = now
        team = s._find_team(state, team_id)
        created = team is None
        if team is None:
            team = {
                "teamId": team_id,
                "name": s.RESEARCH_TEAM_DISPLAY_NAME,
                "description": "由科研组织架构自动同步的系统团队。",
                "purpose": "实时展示科研团队成员、职能与组织通信关系。",
                "status": s.DEFAULT_TEAM_STATUS,
                "members": [],
                "linkedChatRoomId": "",
                "canvasPath": s._relative_path(s._team_canvas_path(team_id)),
                "createdAt": now,
                "updatedAt": now,
            }
            s._apply_team_contract(team, team_kind="research", team_source="research_organization")
            state.setdefault("teams", []).append(team)
        else:
            # Team appeared between the two lock windows: refresh shell metadata
            # only — membership stays under the PATCH aggregation entrypoint.
            team["name"] = s.RESEARCH_TEAM_DISPLAY_NAME
            team["description"] = "由科研组织架构自动同步的系统团队。"
            team["purpose"] = "实时展示科研团队成员、职能与组织通信关系。"
            team["status"] = s.DEFAULT_TEAM_STATUS
            team["canvasPath"] = s._relative_path(s._team_canvas_path(team_id))
            team["updatedAt"] = now
            s._apply_team_contract(team, team_kind="research", team_source="research_organization")
        state["updatedAt"] = str(team.get("updatedAt") or now)
        s._save_index(state)
        s._ensure_team_chat_room_link(team)
        state["updatedAt"] = str(team.get("updatedAt") or now)
        s._save_index(state)
    _debug_logger.warning(
        f"Research organization sync kept Team.members empty; populate members via team settings or bootstrap. "
        f"teamId={team_id} created={created} orgAgentCount={len(list(organization.get('agents') or []))}"
    )
    s._record_team_event(
        "team.research_organization_synced",
        team,
        fields={
            "created": created,
            "memberCount": len(team.get("members") or []),
            "source": "research_organization",
        },
    )
    return s.get_team(team_id)
