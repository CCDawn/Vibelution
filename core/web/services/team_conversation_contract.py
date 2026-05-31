"""Read-only Team to conversation projection contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TeamConversationStatus = Literal[
    "unlinked",
    "linked",
    "room_missing",
    "agent_missing",
    "membership_conflict",
]


@dataclass(frozen=True)
class TeamConversationProjection:
    team_id: str
    linked_room_id: str
    status: TeamConversationStatus
    member_agent_ids: tuple[str, ...]
    room_agent_ids: tuple[str, ...]
    missing_agent_ids: tuple[str, ...]

    def to_api(self) -> dict[str, Any]:
        return {
            "teamId": self.team_id,
            "linkedRoomId": self.linked_room_id,
            "status": self.status,
            "memberAgentIds": list(self.member_agent_ids),
            "roomAgentIds": list(self.room_agent_ids),
            "missingAgentIds": list(self.missing_agent_ids),
            "missingAgentCount": len(self.missing_agent_ids),
        }


def build_team_conversation_projection(
    *,
    team: dict[str, Any],
    linked_room: dict[str, Any] | None,
    agents_by_id: dict[str, Any] | None = None,
) -> TeamConversationProjection:
    team_id = str(team.get("teamId") or "").strip()
    linked_room_id = str(team.get("linkedChatRoomId") or "").strip()
    member_agent_ids = _active_member_agent_ids(team)
    room_agent_ids = _room_agent_ids(linked_room)
    missing_agent_ids = _missing_agent_ids(team, agents_by_id)

    if missing_agent_ids:
        status: TeamConversationStatus = "agent_missing"
    elif not linked_room_id:
        status = "unlinked"
    elif linked_room is None:
        status = "room_missing"
    elif room_agent_ids != member_agent_ids:
        status = "membership_conflict"
    else:
        status = "linked"

    return TeamConversationProjection(
        team_id=team_id,
        linked_room_id=linked_room_id if linked_room is not None or not linked_room_id else linked_room_id,
        status=status,
        member_agent_ids=tuple(member_agent_ids),
        room_agent_ids=tuple(room_agent_ids),
        missing_agent_ids=tuple(missing_agent_ids),
    )


def _active_member_agent_ids(team: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        if str(member.get("agentStatus") or "active").strip().lower() == "stale":
            continue
        ids.append(agent_id)
    return ids


def _room_agent_ids(room: dict[str, Any] | None) -> list[str]:
    if not room:
        return []
    ids: list[str] = []
    for participant in list(room.get("participants") or []):
        if not isinstance(participant, dict):
            continue
        agent_id = str(participant.get("agentId") or "").strip()
        if agent_id:
            ids.append(agent_id)
    return ids


def _missing_agent_ids(team: dict[str, Any], agents_by_id: dict[str, Any] | None) -> list[str]:
    missing: list[str] = []
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agentId") or "").strip()
        if not agent_id:
            continue
        stale = str(member.get("agentStatus") or "active").strip().lower() == "stale"
        absent = agents_by_id is not None and agent_id not in agents_by_id
        if stale or absent:
            missing.append(agent_id)
    return missing
