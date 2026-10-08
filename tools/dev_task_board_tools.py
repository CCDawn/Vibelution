# -*- coding: utf-8 -*-
"""Agent tool for the development-team shared task board.

One tool, six actions. The caller is the team agent itself: the actor is
resolved from ``current_agent_runtime``'s agentId, mapped onto the team's
member row, and every write still goes through ``dev_task_board``'s own
apply_* role gates (the tool layer never widens them). Claims reuse
``apply_claim_with_workspace`` so a claim opens the task worktree and a
failed open rolls the claim back.

``read_task_changes`` extends the board's file list with bounded per-file
diff bodies against ``main`` (untracked files read their first lines and
are labelled as such). The board service file is imported read-only here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Tuple

DEV_TASK_BOARD_TOOL_NAME = "dev_task_board_tool"
_SUPPORTED_ACTIONS = ("create_task", "update_task", "claim_task", "read_task_changes", "complete_task", "rework_task")

# Diff budget: per file, per call. A line itself is width-capped so a
# minified blob cannot blow the payload through a single line.
_MAX_DIFF_LINES_PER_FILE = 200
_MAX_DIFF_LINES_TOTAL = 800
_MAX_DIFF_LINE_WIDTH = 400
_MAX_UNTRACKED_BYTES = 1024 * 1024
_DIFF_CUT_MARK = "…（截断）"

class DevTaskBoardToolError(Exception):
    """Tool-layer failure with a stable machine code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def dev_task_board_tool(
    action: str,
    team_id: str,
    task_id: str = "",
    expected_revision: int = 0,
    subject: Optional[str] = None,
    description: Optional[str] = None,
    write_scopes: Optional[List[str]] = None,
    blocked_by: Optional[List[str]] = None,
    review_note: str = "",
    owner_member_id: str = "",
) -> str:
    """Run one task-board action as the current team agent. Returns compact JSON."""

    try:
        payload = _dispatch(
            action=action,
            team_id=str(team_id or "").strip(),
            task_id=str(task_id or "").strip(),
            expected_revision=_int_revision(expected_revision),
            subject=subject,
            description=description,
            write_scopes=write_scopes,
            blocked_by=blocked_by,
            review_note=str(review_note or ""),
            owner_member_id=str(owner_member_id or "").strip(),
        )
    except DevTaskBoardToolError as exc:
        return json.dumps(
            {"status": "error", "tool": DEV_TASK_BOARD_TOOL_NAME, "code": exc.code, "message": exc.message},
            ensure_ascii=False,
        )
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


# --- dispatch ---------------------------------------------------------------


def _dispatch(
    *,
    action: str,
    team_id: str,
    task_id: str,
    expected_revision: int,
    subject: Optional[str],
    description: Optional[str],
    write_scopes: Optional[List[str]],
    blocked_by: Optional[List[str]],
    review_note: str,
    owner_member_id: str,
) -> dict[str, Any]:
    normalized_action = str(action or "").strip()
    if normalized_action not in _SUPPORTED_ACTIONS:
        raise DevTaskBoardToolError(
            "INVALID_ACTION",
            "action 只支持：" + ", ".join(_SUPPORTED_ACTIONS) + "。",
        )
    if not team_id:
        raise DevTaskBoardToolError("MISSING_TEAM", "缺少 teamId：agent 应从自己的团队上下文里带上团队 ID。")

    team, member = _resolve_actor(team_id)
    actor_member_id = str(member.get("memberId") or "")
    role = str(member.get("role") or "")

    if normalized_action == "create_task":
        payload = _create_task(
            team_id,
            actor_member_id=actor_member_id,
            subject=str(subject or ""),
            description=str(description or ""),
            write_scopes=write_scopes,
            blocked_by=blocked_by,
            owner_member_id=owner_member_id,
        )
    elif normalized_action == "read_task_changes":
        from core.web.services.team.dev_task_board import PLANNER_ROLE, REVIEWER_ROLE

        if role not in {PLANNER_ROLE, REVIEWER_ROLE}:
            raise DevTaskBoardToolError(
                "ROLE_DENIED",
                f"当前角色（{role or '未知'}）不能读任务改动：read_task_changes 只开放给规划师与评审员。",
            )
        if not task_id:
            raise DevTaskBoardToolError("MISSING_TASK", "缺少 taskId。")
        return _read_changes(team_id, task_id)
    else:
        if not task_id:
            raise DevTaskBoardToolError("MISSING_TASK", f"{normalized_action} 需要 taskId。")
        if expected_revision <= 0:
            raise DevTaskBoardToolError(
                "MISSING_REVISION",
                f"{normalized_action} 需要 expectedRevision（用最近一次看到的任务 revision，防止并发覆盖）。",
            )
        board_action = {
            "update_task": "update",
            "claim_task": "claim",
            "complete_task": "complete",
            "rework_task": "rework",
        }[normalized_action]
        payload = _mutate(
            team_id,
            task_id,
            actor_member_id=actor_member_id,
            board_action=board_action,
            expected_revision=expected_revision,
            subject=subject,
            description=description,
            write_scopes=write_scopes,
            blocked_by=blocked_by,
            review_note=review_note,
        )
    target_id = _newest_task_id(payload) if normalized_action == "create_task" else task_id
    result = {
        "action": normalized_action,
        "teamId": team_id,
        "taskId": target_id,
        **_task_summary(payload, target_id),
    }
    if normalized_action == "claim_task":
        result.update(
            _claim_workspace_guidance(
                str(result.get("workspacePath") or ""),
                str(result.get("workspaceBranch") or ""),
            )
        )
    return result


def _claim_workspace_guidance(workspace_path: str, workspace_branch: str) -> dict:
    """Claim-turn write routing: the board stores ``.worktrees/<slug>`` relative,
    but the claiming engineer's tools resolve relative paths against the agent's
    private workspace for the rest of this turn (workspace binding only re-runs
    at next turn start), so writes would land in a parallel private tree. The
    absolute worktree path is inside PROJECT_ROOT and therefore within the
    agent-tool write boundary, so routing the model to absolute paths fixes the
    claim turn without widening any permission."""

    directory = _resolve_task_worktree(workspace_path, workspace_branch)
    if directory is None:
        return {
            "message": (
                "任务已认领，但任务工作区目录尚未就绪；本轮不要写任何文件，"
                "下一回合工作区会自动绑定。"
            )
        }
    return {
        "workspaceAbsolutePath": str(directory),
        "message": (
            "任务已认领，任务工作区已打开。本任务的读写都必须落在这个绝对路径下："
            f"{directory}。apply_patch_tool 的 cwd、apply_diff_edit_tool 的 file_path、"
            "run_test_for_tool 的 source_path 都用该目录下的绝对路径；"
            "相对路径会解析到别的根目录，属于写错位置。"
        ),
    }


# --- actor resolution -------------------------------------------------------


def _resolve_actor(team_id: str) -> Tuple[dict, dict]:
    """agentId -> team member row. Fail closed on any missing link."""

    from core.web.services import agent_directory_service, team_service
    from core.web.services.team_service import TeamNotFoundError

    runtime = agent_directory_service.current_agent_runtime() or {}
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        raise DevTaskBoardToolError(
            "NO_AGENT_CONTEXT",
            "当前没有 Agent 身份上下文：任务板工具只能在开发团队 Agent 的回合内调用。",
        )
    try:
        team = team_service.get_team(team_id)
    except TeamNotFoundError as exc:
        raise DevTaskBoardToolError("TEAM_NOT_FOUND", str(exc)) from exc
    for member in list(team.get("members") or []):
        if not isinstance(member, dict):
            continue
        if str(member.get("agentId") or "").strip() != agent_id:
            continue
        if str(member.get("agentStatus") or "active") != "active":
            break
        return team, member
    raise DevTaskBoardToolError(
        "NOT_TEAM_MEMBER",
        "当前 Agent 不是这个开发团队的活跃成员，不能操作它的任务板。",
    )


# --- write actions ----------------------------------------------------------


def _create_task(
    team_id: str,
    *,
    actor_member_id: str,
    subject: str,
    description: str,
    write_scopes: Optional[List[str]],
    blocked_by: Optional[List[str]],
    owner_member_id: str,
) -> dict[str, Any]:
    from core.web.services.team.dev_task_board import create_dev_task

    return _run_board(
        lambda: create_dev_task(
            team_id,
            actor_member_id=actor_member_id,
            subject=subject,
            description=description,
            write_scopes=_clean_str_list(write_scopes),
            blocked_by=_clean_str_list(blocked_by),
            owner_member_id=owner_member_id,
        )
    )


def _mutate(
    team_id: str,
    task_id: str,
    *,
    actor_member_id: str,
    board_action: str,
    expected_revision: int,
    subject: Optional[str],
    description: Optional[str],
    write_scopes: Optional[List[str]],
    blocked_by: Optional[List[str]],
    review_note: str,
) -> dict[str, Any]:
    from core.web.services.team.dev_task_board import mutate_dev_task

    return _run_board(
        lambda: mutate_dev_task(
            team_id,
            task_id,
            actor_member_id=actor_member_id,
            action=board_action,
            expected_revision=expected_revision,
            subject=subject if board_action == "update" else None,
            description=description if board_action == "update" else None,
            write_scopes=_clean_str_list(write_scopes) if board_action == "update" and write_scopes is not None else None,
            blocked_by=_clean_str_list(blocked_by) if board_action == "update" and blocked_by is not None else None,
            review_note=review_note,
        )
    )


def _run_board(call):
    from core.web.services.team.dev_task_board import DevTaskBoardError, DevTaskStaleRevision
    from core.web.services.team_service import TeamServiceError

    try:
        return call()
    except DevTaskStaleRevision as exc:
        raise DevTaskBoardToolError(
            "STALE_REVISION",
            f"{exc} 请先重新读取任务（read_task_changes 或看板摘要），用最新 revision 重试。",
        ) from exc
    except DevTaskBoardError as exc:
        code = "ROLE_DENIED" if "当前角色不能" in str(exc) else "BOARD_REJECTED"
        raise DevTaskBoardToolError(code, str(exc)) from exc
    except TeamServiceError as exc:
        raise DevTaskBoardToolError("TEAM_REJECTED", str(exc)) from exc


# --- read_task_changes ------------------------------------------------------


def _read_changes(team_id: str, task_id: str) -> dict[str, Any]:
    from core.web.services.team.dev_task_board import (
        _checked_task_worktree,
        _git_at,
        _without_pinned_git_env,
        read_dev_task_changes,
    )
    from core.web.services import team_service

    board_payload = _run_board(lambda: _list_payload(team_id))
    task = next((item for item in board_payload.get("tasks") or [] if item.get("id") == task_id), None)
    if task is None:
        raise DevTaskBoardToolError("TASK_NOT_FOUND", "任务不存在。")

    workspace_path = str(task.get("workspacePath") or "")
    workspace_branch = str(task.get("workspaceBranch") or "")
    base = {
        "action": "read_task_changes",
        "teamId": team_id,
        "taskId": task_id,
        "taskStatus": str(task.get("status") or ""),
        "workspacePath": workspace_path,
        "workspaceBranch": workspace_branch,
    }
    changes_payload = read_dev_task_changes(
        team_service.PROJECT_ROOT,
        workspace_path=workspace_path,
        workspace_branch=workspace_branch,
    )
    changes = list(changes_payload.get("changes") or [])
    if not changes_payload.get("available"):
        return {
            **base,
            "available": False,
            "message": "任务工作区当前读不出来（可能还没认领或 worktree 已失效），diff 内容省略。",
            "changes": [],
        }
    if not workspace_path and not workspace_branch:
        return {
            **base,
            "available": True,
            "workspace": False,
            "message": "这个任务还没有工作区（未认领），没有改动可读。",
            "changes": [],
        }

    directory = _resolve_task_worktree(workspace_path, workspace_branch)
    if directory is None:
        return {
            **base,
            "available": False,
            "message": "任务工作区校验失败，diff 内容省略。",
            "changes": [{"path": item.get("path"), "status": item.get("status")} for item in changes],
        }

    budget = {"used": 0, "exhausted": False}
    enriched: list[dict[str, Any]] = []
    for item in changes:
        path = str(item.get("path") or "")
        status = str(item.get("status") or "")
        body, truncated, note = _bounded_diff(directory, path, status, budget)
        entry: dict[str, Any] = {"path": path, "status": status}
        if note:
            entry["note"] = note
        entry["diff"] = body
        entry["diffTruncated"] = truncated
        enriched.append(entry)
    return {
        **base,
        "available": True,
        "workspace": True,
        "fileCount": len(enriched),
        "fileListTruncated": int(changes_payload.get("truncated") or 0),
        "diffBudget": {"perFileLines": _MAX_DIFF_LINES_PER_FILE, "totalLines": _MAX_DIFF_LINES_TOTAL, "usedLines": budget["used"]},
        "changes": enriched,
    }


def _list_payload(team_id: str) -> dict[str, Any]:
    from core.web.services.team.dev_task_board import list_dev_tasks

    return list_dev_tasks(team_id)


def _resolve_task_worktree(workspace_path: str, workspace_branch: str):
    """Same checked resolution the board's own change reader uses."""

    from core.web.services import team_service
    from core.web.services.team.dev_task_board import _checked_task_worktree, _without_pinned_git_env

    try:
        with _without_pinned_git_env():
            return _checked_task_worktree(team_service.PROJECT_ROOT, workspace_path, workspace_branch)
    except Exception:
        return None


def _bounded_diff(directory: Path, path: str, status: str, budget: dict) -> tuple[str, bool, str]:
    """One file's diff body within the line budget. Never raises."""

    if budget["exhausted"]:
        return "", True, "diff 行数总量已用完，此文件内容省略。"
    remaining_total = _MAX_DIFF_LINES_TOTAL - budget["used"]
    allowed = min(_MAX_DIFF_LINES_PER_FILE, remaining_total)
    if allowed <= 0:
        budget["exhausted"] = True
        return "", True, "diff 行数总量已用完，此文件内容省略。"

    if status == "untracked":
        lines, truncated, note = _untracked_head(directory, path, allowed)
    else:
        lines, truncated, note = _git_diff_lines(directory, path, allowed)
    taken = len(lines)
    budget["used"] += taken
    if budget["used"] >= _MAX_DIFF_LINES_TOTAL:
        budget["exhausted"] = True
        if taken < len(lines) or truncated:
            truncated = True
    return "\n".join(lines), truncated, note


def _git_diff_lines(directory: Path, path: str, allowed: int) -> tuple[list[str], bool, str]:
    from core.web.services.team.dev_task_board import _git_at, _without_pinned_git_env

    try:
        with _without_pinned_git_env():
            result = _git_at(directory, ["diff", "main", "--", path], timeout=30.0)
    except Exception as exc:  # pragma: no cover - git 崩溃时降级为无内容
        return [], True, f"diff 读取失败：{exc}"
    if result.returncode != 0:
        return [], True, "diff 读取失败。"
    lines, truncated = _cap_lines(str(result.stdout or ""), allowed, "diff 行数达到单文件上限")
    return lines, truncated, ""


def _untracked_head(directory: Path, path: str, allowed: int) -> tuple[list[str], bool, str]:
    note = "未跟踪"
    target = (directory / path).resolve()
    try:
        target.relative_to(directory.resolve())
    except ValueError:
        return [], True, "路径越出任务工作区，内容省略。"
    if not target.is_file():
        return [], True, "未跟踪路径不是文件，内容省略。"
    try:
        if target.stat().st_size > _MAX_UNTRACKED_BYTES:
            return [], True, "未跟踪文件过大（超过 1MB），内容省略。"
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], True, f"未跟踪文件读取失败：{exc}"
    body = text.splitlines()
    head = body[:allowed]
    truncated = len(body) > len(head)
    extra = f"，且达到行数上限" if truncated else ""
    return head, truncated, f"{note}{extra}"


def _cap_lines(text: str, allowed: int, reason: str) -> tuple[list[str], bool]:
    lines = [
        (line if len(line) <= _MAX_DIFF_LINE_WIDTH else line[:_MAX_DIFF_LINE_WIDTH] + _DIFF_CUT_MARK)
        for line in text.splitlines()
    ]
    head = lines[:allowed]
    return head, len(lines) > len(head)


# --- payload helpers --------------------------------------------------------


def _task_summary(payload: dict[str, Any], task_id: str) -> dict[str, Any]:
    view = next(
        (item for item in list(payload.get("tasks") or []) if isinstance(item, dict) and item.get("id") == task_id),
        None,
    )
    if view is None:
        return {}
    return {
        "revision": int(view.get("revision") or 0),
        "subject": str(view.get("subject") or ""),
        "taskStatus": str(view.get("status") or ""),
        "ownerMemberId": str(view.get("ownerMemberId") or ""),
        "ownerName": str(view.get("ownerName") or ""),
        "blockedBy": list(view.get("blockedBy") or []),
        "ready": bool(view.get("ready")),
        "workspacePath": str(view.get("workspacePath") or ""),
        "workspaceBranch": str(view.get("workspaceBranch") or ""),
        "reviewNote": str(view.get("reviewNote") or ""),
    }


def _newest_task_id(payload: dict[str, Any]) -> str:
    def number(item: dict[str, Any]) -> int:
        raw = str(item.get("id") or "")
        return int(raw[5:]) if raw.startswith("task-") and raw[5:].isdigit() else -1

    tasks = [item for item in list(payload.get("tasks") or []) if isinstance(item, dict)]
    return max(tasks, key=number).get("id", "") if tasks else ""


def _int_revision(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item or "").strip() for item in values if str(item or "").strip()]


__all__ = ["DevTaskBoardToolError", "dev_task_board_tool"]
