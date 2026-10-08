"""Shared task board for the development-team template.

The linked chat room remains the conversation record. This file stores task
snapshots only: revision, owner, blockers, and advisory write scopes.
Overlapping scopes are reported on the view and never block a claim.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.web.services.team import team_store
from core.web.services.team_service import (
    TeamServiceError,
    get_team,
    utc_now_iso,
)

SCHEMA_VERSION = 1
MAX_OPEN_TASKS = 200
MAX_SUBJECT = 200
MAX_DESCRIPTION = 4000
MAX_REVIEW_NOTE = 500
MAX_SCOPES = 8
MAX_BLOCKERS = 20
MAX_SCOPE_LENGTH = 180
PLANNER_ROLE = "规划师"
REVIEWER_ROLE = "评审员"
ENGINEER_ROLES = frozenset({"开发工程师 A", "开发工程师 B"})
ASSIGNABLE_ROLES = ENGINEER_ROLES | {REVIEWER_ROLE}
ACTIONS = frozenset({"assign", "claim", "complete", "rework", "update", "delete"})
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class DevTaskBoardError(TeamServiceError):
    """Raised when a development-team task request is invalid."""


class DevTaskStaleRevision(DevTaskBoardError):
    """Raised when a write uses an older task revision."""


def empty_dev_task_board() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "nextNumber": 1, "updatedAt": "", "tasks": []}


def list_dev_tasks(team_id: str) -> dict[str, Any]:
    return _with_board(team_id, None)


def create_dev_task(
    team_id: str,
    *,
    actor_member_id: str,
    subject: str,
    description: str = "",
    write_scopes: list[str] | None = None,
    blocked_by: list[str] | None = None,
    owner_member_id: str = "",
) -> dict[str, Any]:
    def mutate(team: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
        return apply_create(
            team,
            board,
            actor_member_id=actor_member_id,
            subject=subject,
            description=description,
            write_scopes=write_scopes,
            blocked_by=blocked_by,
            owner_member_id=owner_member_id,
            now=utc_now_iso(),
        )

    return _with_board(team_id, mutate)


def mutate_dev_task(
    team_id: str,
    task_id: str,
    *,
    actor_member_id: str,
    action: str,
    expected_revision: int,
    owner_member_id: str = "",
    subject: str | None = None,
    description: str | None = None,
    write_scopes: list[str] | None = None,
    blocked_by: list[str] | None = None,
    review_note: str = "",
) -> dict[str, Any]:
    def mutate(team: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
        return apply_action(
            team,
            board,
            task_id=task_id,
            actor_member_id=actor_member_id,
            action=action,
            expected_revision=expected_revision,
            owner_member_id=owner_member_id,
            subject=subject,
            description=description,
            write_scopes=write_scopes,
            blocked_by=blocked_by,
            review_note=review_note,
            now=utc_now_iso(),
        )

    return _with_board(team_id, mutate)


def apply_create(
    team: dict[str, Any],
    board: dict[str, Any],
    *,
    actor_member_id: str,
    subject: str,
    description: str = "",
    write_scopes: list[str] | None = None,
    blocked_by: list[str] | None = None,
    owner_member_id: str = "",
    now: str = "",
) -> dict[str, Any]:
    _require_dev_team(team)
    actor = _require_actor(team, actor_member_id)
    if str(actor.get("role") or "") != PLANNER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    open_count = sum(1 for task in _tasks(board) if task["status"] != "deleted")
    if open_count >= MAX_OPEN_TASKS:
        raise DevTaskBoardError("任务板已满。")
    owner = _assignable_owner(team, owner_member_id)
    normalized_subject = _subject(subject)
    normalized_description = _bounded_text(description, MAX_DESCRIPTION, "说明太长。")
    normalized_scopes = _write_scopes(write_scopes or [])
    blockers = [str(item) for item in (blocked_by or [])]
    previous_number = board.get("nextNumber")
    task = {
        "id": _allocate_id(board),
        "revision": 1,
        "subject": normalized_subject,
        "description": normalized_description,
        "status": "pending",
        "ownerMemberId": str(owner.get("memberId") or "") if owner else "",
        "blockedBy": blockers,
        "writeScopes": normalized_scopes,
        "reviewNote": "",
        "updatedAt": now,
    }
    tasks = [*_tasks(board), task]
    try:
        _assert_dependencies(tasks)
    except DevTaskBoardError:
        board["nextNumber"] = previous_number
        raise
    board["tasks"] = tasks
    board["updatedAt"] = now
    return board


def apply_action(
    team: dict[str, Any],
    board: dict[str, Any],
    *,
    task_id: str,
    actor_member_id: str,
    action: str,
    expected_revision: int,
    owner_member_id: str = "",
    subject: str | None = None,
    description: str | None = None,
    write_scopes: list[str] | None = None,
    blocked_by: list[str] | None = None,
    review_note: str = "",
    now: str = "",
) -> dict[str, Any]:
    _require_dev_team(team)
    normalized_action = str(action or "").strip()
    if normalized_action not in ACTIONS:
        raise DevTaskBoardError("不支持这个任务操作。")
    actor = _require_actor(team, actor_member_id)
    task = _require_task(board, task_id)
    _require_revision(task, expected_revision)
    role = str(actor.get("role") or "")
    if normalized_action == "claim":
        _claim(board, task, actor)
    elif normalized_action == "assign":
        _assign(team, task, role, owner_member_id)
    elif normalized_action == "complete":
        _complete(task, role, review_note)
    elif normalized_action == "rework":
        _rework(task, role, review_note)
    elif normalized_action == "delete":
        _delete(board, task, role)
    else:
        _update(board, task, role, subject, description, write_scopes, blocked_by)
    task["revision"] = int(task["revision"]) + 1
    task["updatedAt"] = now
    board["updatedAt"] = now
    return board


def dev_task_views(team: dict[str, Any], board: dict[str, Any]) -> list[dict[str, Any]]:
    members = _members_by_id(team)
    tasks = _tasks(board)
    visible = [task for task in tasks if task["status"] != "deleted"]
    views: list[dict[str, Any]] = []
    for task in sorted(visible, key=_task_sort_key):
        owner = members.get(str(task.get("ownerMemberId") or ""))
        views.append(
            {
                "id": task["id"],
                "revision": int(task["revision"]),
                "subject": task["subject"],
                "description": task["description"],
                "status": task["status"],
                "ownerMemberId": str(task.get("ownerMemberId") or ""),
                "ownerName": str(owner.get("agentName") or "") if owner else "",
                "ownerRole": str(owner.get("role") or "") if owner else "",
                "blockedBy": list(task.get("blockedBy") or []),
                "writeScopes": list(task.get("writeScopes") or []),
                "reviewNote": str(task.get("reviewNote") or ""),
                "ready": _ready(task, tasks),
                "writeScopeWarnings": _scope_warnings(task, tasks),
                "updatedAt": str(task.get("updatedAt") or ""),
            }
        )
    return views


def _with_board(team_id: str, mutator: Any) -> dict[str, Any]:
    from core.web.services import team_service

    team = get_team(team_id)
    _require_dev_team(team)
    path = team_store._dev_task_board_path(str(team.get("teamId") or team_id))
    with team_service._TEAM_LOCK:
        board = _read_board(path)
        if mutator is not None:
            board = mutator(team, board)
            board["schemaVersion"] = SCHEMA_VERSION
            board["updatedAt"] = utc_now_iso()
            team_store._write_json(path, board)
    return _public_payload(team, board)


def _public_payload(team: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": str(team.get("teamId") or ""),
        "tasks": dev_task_views(team, board),
        "updatedAt": str(board.get("updatedAt") or ""),
    }


def _read_board(path: Any) -> dict[str, Any]:
    if not path.exists():
        return empty_dev_task_board()
    try:
        data = team_store._read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise DevTaskBoardError("任务板文件损坏。") from exc
    if int(data.get("schemaVersion") or 0) != SCHEMA_VERSION or not isinstance(data.get("tasks"), list):
        raise DevTaskBoardError("任务板文件损坏。")
    if not isinstance(data.get("nextNumber"), int):
        raise DevTaskBoardError("任务板文件损坏。")
    return data


def _require_dev_team(team: dict[str, Any]) -> None:
    if str(team.get("teamTemplateId") or "") != "dev-team":
        raise DevTaskBoardError("只有开发团队有共享任务板。")


def _members(team: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(team.get("members") or []) if isinstance(item, dict)]


def _members_by_id(team: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("memberId") or ""): item for item in _members(team) if str(item.get("memberId") or "")}


def _require_actor(team: dict[str, Any], member_id: str) -> dict[str, Any]:
    member = _members_by_id(team).get(str(member_id or "").strip())
    if member is None or str(member.get("agentStatus") or "active") != "active":
        raise DevTaskBoardError("当前成员不在这个开发团队里。")
    return member


def _assignable_owner(team: dict[str, Any], member_id: str) -> dict[str, Any] | None:
    normalized = str(member_id or "").strip()
    if not normalized:
        return None
    member = _members_by_id(team).get(normalized)
    if member is None or str(member.get("role") or "") not in ASSIGNABLE_ROLES:
        raise DevTaskBoardError("负责人要是开发工程师或评审员。")
    if str(member.get("agentStatus") or "active") != "active":
        raise DevTaskBoardError("负责人要是开发工程师或评审员。")
    return member


def _tasks(board: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(board.get("tasks") or []) if isinstance(item, dict)]


def _allocate_id(board: dict[str, Any]) -> str:
    number = int(board.get("nextNumber") or 1)
    used = [
        int(str(task.get("id") or "")[5:])
        for task in _tasks(board)
        if str(task.get("id") or "").startswith("task-") and str(task.get("id") or "")[5:].isdigit()
    ]
    if used:
        number = max(number, max(used) + 1)
    board["nextNumber"] = number + 1
    return f"task-{number}"


def _require_task(board: dict[str, Any], task_id: str) -> dict[str, Any]:
    normalized = str(task_id or "").strip()
    for task in _tasks(board):
        if task.get("id") == normalized and task.get("status") != "deleted":
            return task
    raise DevTaskBoardError("任务不存在。")


def _require_revision(task: dict[str, Any], expected_revision: int) -> None:
    if int(expected_revision) != int(task.get("revision") or 0):
        raise DevTaskStaleRevision("任务版本已变，请按最新版本再试。")


def _claim(board: dict[str, Any], task: dict[str, Any], actor: dict[str, Any]) -> None:
    if str(actor.get("role") or "") not in ENGINEER_ROLES:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    if not _ready(task, _tasks(board)):
        raise DevTaskBoardError("任务还没到可认领的状态。")
    owner_id = str(task.get("ownerMemberId") or "")
    actor_id = str(actor.get("memberId") or "")
    if owner_id and owner_id != actor_id:
        raise DevTaskBoardError("这个任务已经有负责人。")
    task["ownerMemberId"] = actor_id
    task["status"] = "in_progress"


def _assign(team: dict[str, Any], task: dict[str, Any], role: str, owner_member_id: str) -> None:
    if role != PLANNER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    if task["status"] in {"completed", "deleted"}:
        raise DevTaskBoardError("这个任务不能再改派。")
    owner = _assignable_owner(team, owner_member_id)
    next_owner = str(owner.get("memberId") or "") if owner else ""
    previous = str(task.get("ownerMemberId") or "")
    task["ownerMemberId"] = next_owner
    if next_owner != previous and task["status"] == "in_progress":
        task["status"] = "pending"
    if not next_owner and task["status"] == "rework":
        task["status"] = "pending"


def _complete(task: dict[str, Any], role: str, review_note: str) -> None:
    if role != REVIEWER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    if task["status"] not in {"in_progress", "rework"}:
        raise DevTaskBoardError("这个任务还不能收口。")
    task["status"] = "completed"
    task["reviewNote"] = _bounded_text(review_note, MAX_REVIEW_NOTE, "评审说明太长。")


def _rework(task: dict[str, Any], role: str, review_note: str) -> None:
    if role != REVIEWER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    if task["status"] not in {"in_progress", "completed"}:
        raise DevTaskBoardError("这个任务还不能退回。")
    if not str(task.get("ownerMemberId") or ""):
        raise DevTaskBoardError("退回前要有负责人。")
    task["status"] = "rework"
    task["reviewNote"] = _bounded_text(review_note, MAX_REVIEW_NOTE, "评审说明太长。")


def _delete(board: dict[str, Any], task: dict[str, Any], role: str) -> None:
    if role != PLANNER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    dependents = [
        other["id"]
        for other in _tasks(board)
        if other.get("status") != "deleted" and task["id"] in list(other.get("blockedBy") or [])
    ]
    if dependents:
        raise DevTaskBoardError("还有别的任务依赖它，不能删除。")
    task["status"] = "deleted"


def _update(
    board: dict[str, Any],
    task: dict[str, Any],
    role: str,
    subject: str | None,
    description: str | None,
    write_scopes: list[str] | None,
    blocked_by: list[str] | None,
) -> None:
    if role != PLANNER_ROLE:
        raise DevTaskBoardError("当前角色不能做这个操作。")
    if task["status"] in {"completed", "deleted"}:
        raise DevTaskBoardError("这个任务不能再改。")
    if subject is not None:
        task["subject"] = _subject(subject)
    if description is not None:
        task["description"] = _bounded_text(description, MAX_DESCRIPTION, "说明太长。")
    if write_scopes is not None:
        task["writeScopes"] = _write_scopes(write_scopes)
    if blocked_by is not None:
        previous = list(task.get("blockedBy") or [])
        task["blockedBy"] = [str(item) for item in blocked_by]
        try:
            _assert_dependencies(_tasks(board))
        except DevTaskBoardError:
            task["blockedBy"] = previous
            raise


def _subject(value: str) -> str:
    text = _bounded_text(value, MAX_SUBJECT, "主题太长。")
    if not text:
        raise DevTaskBoardError("主题不能为空。")
    return text


def _bounded_text(value: str, limit: int, message: str) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise DevTaskBoardError(message)
    return text


def _write_scopes(values: list[str]) -> list[str]:
    scopes: list[str] = []
    for raw in values:
        scope = _normalize_scope(raw)
        if scope and scope not in scopes:
            scopes.append(scope)
    if len(scopes) > MAX_SCOPES:
        raise DevTaskBoardError("写范围太多。")
    return scopes


def _normalize_scope(raw: str) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    if not text:
        return ""
    parts = [part for part in text.split("/") if part]
    if _DRIVE_PREFIX.match(text) or ".." in parts or any(part in {"", "."} for part in text.split("/")):
        raise DevTaskBoardError("写范围只能是工作区里的相对路径。")
    normalized = "/".join(parts)
    if len(normalized) > MAX_SCOPE_LENGTH:
        raise DevTaskBoardError("写范围太长。")
    return normalized


def _assert_dependencies(tasks: list[dict[str, Any]]) -> None:
    alive = {str(task.get("id") or ""): task for task in tasks if task.get("status") != "deleted"}
    message = "任务依赖必须指向还在的任务，并且不能成环。"
    for task in alive.values():
        blockers: list[str] = []
        for raw in list(task.get("blockedBy") or []):
            blocker_id = str(raw or "").strip()
            if not blocker_id or blocker_id in blockers:
                continue
            if blocker_id == task.get("id") or blocker_id not in alive:
                raise DevTaskBoardError(message)
            blockers.append(blocker_id)
        if len(blockers) > MAX_BLOCKERS:
            raise DevTaskBoardError("依赖太多。")
        task["blockedBy"] = blockers
    color = {task_id: 0 for task_id in alive}

    def visit(task_id: str) -> None:
        state = color[task_id]
        if state == 1:
            raise DevTaskBoardError(message)
        if state == 2:
            return
        color[task_id] = 1
        for blocker_id in list(alive[task_id].get("blockedBy") or []):
            visit(str(blocker_id))
        color[task_id] = 2

    for task_id in list(alive):
        visit(task_id)


def _ready(task: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
    if task.get("status") not in {"pending", "rework"}:
        return False
    by_id = {str(item.get("id") or ""): item for item in tasks}
    for blocker_id in list(task.get("blockedBy") or []):
        blocker = by_id.get(str(blocker_id))
        if blocker is None or blocker.get("status") != "completed":
            return False
    return True


def _scope_warnings(task: dict[str, Any], tasks: list[dict[str, Any]]) -> list[str]:
    if task.get("status") in {"completed", "deleted"}:
        return []
    warnings: list[str] = []
    for other in tasks:
        if other.get("id") == task.get("id") or other.get("status") in {"completed", "deleted"}:
            continue
        if _scopes_overlap(list(task.get("writeScopes") or []), list(other.get("writeScopes") or [])):
            warnings.append(f"与 {other.get('id')} 的写范围重叠")
    return warnings


def _scopes_overlap(left: list[str], right: list[str]) -> bool:
    for item in left:
        for other in right:
            if item == other or item.startswith(f"{other}/") or other.startswith(f"{item}/"):
                return True
    return False


def _task_sort_key(task: dict[str, Any]) -> tuple[int, str]:
    raw = str(task.get("id") or "")
    if raw.startswith("task-") and raw[5:].isdigit():
        return (int(raw[5:]), raw)
    return (10**9, raw)
