"""Task-scoped ephemeral teams built on the dev-team template.

An ephemeral team is a one-shot instantiation of the dev-team template bound
to a single topic: creation materializes the usual planner/engineer/reviewer
roster, opens the planned chat room, and seeds the shared task board with the
first task. The board owns the lifecycle — once no open task is left, the
team archives itself (see ``dev_task_board._maybe_dissolve_ephemeral_team``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

EPHEMERAL_TEAM_KIND = "ephemeral"
EPHEMERAL_TEAM_SOURCE = "ephemeral_task"
EPHEMERAL_TEAM_TEMPLATE_ID = "dev-team"
EPHEMERAL_TEAM_CATEGORY = "临时任务团队"
DEFAULT_TEAM_NAME = "临时组队"
_MAX_TOPIC = 2000
_MAX_TASK_TITLE = 120
_MAX_DEFAULT_NAME_TOPIC = 40


class EphemeralTeamError(ValueError):
    """Raised when an ephemeral team request is invalid."""


def create_ephemeral_team(project_root: Path | str | None = None, *, topic: str, name: str = "") -> dict[str, Any]:
    """Create one task-scoped team from the dev-team template and seed its board.

    Reuses ``instantiate_team_template`` for the whole materialization (agents,
    members, chat room, canvas) and only overrides the membership contract:
    kind ``ephemeral`` / source ``ephemeral_task`` / purpose = topic, while
    ``teamTemplateId`` stays ``dev-team`` so the shared task board accepts the
    team. The first dev task carries the topic as its description and a topic-
    derived subject.
    """

    from core.web.services import (
        agent_directory_service,
        chat_room_service,
        session_service,
        team_service,
        team_template_service,
    )
    from core.web.services.team import dev_task_board

    normalized_topic = _normalized_topic(topic)
    team_name = _team_name(name or _default_team_name(normalized_topic))
    _sync_project_roots(
        project_root,
        agent_directory_service,
        chat_room_service,
        session_service,
        team_service,
        team_template_service,
    )

    instantiated = team_template_service.instantiate_team_template(
        EPHEMERAL_TEAM_TEMPLATE_ID,
        name=team_name,
        team_kind=EPHEMERAL_TEAM_KIND,
        team_category=EPHEMERAL_TEAM_CATEGORY,
        team_source=EPHEMERAL_TEAM_SOURCE,
        team_purpose=normalized_topic,
    )
    team = dict(instantiated.get("team") or {})
    team_id = str(team.get("teamId") or "").strip()
    if not team_id:
        raise EphemeralTeamError("Ephemeral team materialization did not return a Team.")
    board = dev_task_board.create_dev_task(
        team_id,
        actor_member_id=_planner_member_id(team),
        subject=_task_title(normalized_topic),
        description=normalized_topic,
    )
    tasks = [item for item in list(board.get("tasks") or []) if isinstance(item, dict)]
    return {
        "schemaVersion": 1,
        "topic": normalized_topic,
        "team": team_service.get_team(team_id),
        "roomId": str(team.get("linkedChatRoomId") or "").strip(),
        "taskId": str(tasks[0].get("id") or "") if tasks else "",
        "board": board,
        "updatedAt": team_template_service.utc_now_iso(),
    }


def _normalized_topic(topic: str) -> str:
    text = trim_lines(str(topic or ""), max_lines=4).strip()
    if not text:
        raise EphemeralTeamError("Topic is required for an ephemeral team.")
    if len(text) > _MAX_TOPIC:
        text = text[:_MAX_TOPIC].rstrip()
    return text


def _default_team_name(topic: str) -> str:
    headline = " ".join(str(topic or "").split())
    if not headline:
        return DEFAULT_TEAM_NAME
    return f"临时组队·{headline[:_MAX_DEFAULT_NAME_TOPIC]}".strip()


def _team_name(name: str) -> str:
    return trim_lines(str(name or ""), max_lines=1).strip() or DEFAULT_TEAM_NAME


def _task_title(topic: str) -> str:
    headline = " ".join(str(topic or "").split())
    if len(headline) > _MAX_TASK_TITLE:
        headline = headline[:_MAX_TASK_TITLE].rstrip()
    return headline or "推进临时任务"


def _planner_member_id(team: dict[str, Any]) -> str:
    from core.web.services.team import dev_task_board

    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        member_id = str(member.get("memberId") or "").strip()
        if member_id and str(member.get("role") or "").strip() == dev_task_board.PLANNER_ROLE:
            return member_id
    raise EphemeralTeamError("Ephemeral team materialization did not return a planner member.")


def _sync_project_roots(project_root: Path | str | None, *services: Any) -> None:
    if project_root is None:
        return
    root = Path(project_root)
    for service in services:
        service.PROJECT_ROOT = root
