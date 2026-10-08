# -*- coding: utf-8 -*-
"""Codex-style transient planning tools."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


_VALID_PLAN_STATUSES = {"pending", "in_progress", "completed"}


def _workspace_root() -> Path:
    from tools.shell_tools import _get_workspace_root

    return _get_workspace_root()


def _safe_plan_id(value: str) -> str:
    raw = str(value or "current").strip() or "current"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("._-")
    return safe or "current"


def _coerce_plan_items(plan: Any) -> tuple[List[Dict[str, str]], str]:
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError as exc:
            return [], f"plan 不是有效 JSON：{exc}"
    if not isinstance(plan, list):
        return [], "plan 需要是列表，每项包含 step 和 status。"

    normalized: List[Dict[str, str]] = []
    for index, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            return [], f"plan 第 {index} 项不是对象。"
        step = str(item.get("step") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if not step:
            return [], f"plan 第 {index} 项缺少 step。"
        if status not in _VALID_PLAN_STATUSES:
            return [], (
                f"plan 第 {index} 项 status 无效：{status or '空'}。"
                "可用状态：pending, in_progress, completed。"
            )
        normalized.append({"step": step, "status": status})

    in_progress_count = sum(1 for item in normalized if item["status"] == "in_progress")
    if in_progress_count > 1:
        return [], "同一份 plan 最多只能有一个 in_progress 项。"
    return normalized, ""


def plan_update_tool(plan: Any, explanation: str = "", plan_id: str = "current") -> str:
    """Update a transient Codex-style plan in the active workspace."""
    normalized, error = _coerce_plan_items(plan)
    if error:
        return json.dumps(
            {
                "status": "error",
                "code": "INVALID_PLAN",
                "message": error,
                "example": {
                    "plan": [
                        {"step": "审查工具契约", "status": "completed"},
                        {"step": "补齐回归测试", "status": "in_progress"},
                    ],
                    "explanation": "同步当前对齐进度",
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    safe_id = _safe_plan_id(plan_id)
    root = _workspace_root()
    plans_dir = root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / f"{safe_id}.json"
    payload = {
        "planId": safe_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "explanation": str(explanation or "").strip(),
        "plan": normalized,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return json.dumps(
        {
            "status": "ok",
            "planId": safe_id,
            "path": str(path),
            "itemCount": len(normalized),
            "inProgress": [item["step"] for item in normalized if item["status"] == "in_progress"],
            "completedCount": sum(1 for item in normalized if item["status"] == "completed"),
        },
        ensure_ascii=False,
        indent=2,
    )


def _current_session_id() -> str:
    from core.web.services.agent_directory_service import current_agent_runtime

    runtime = current_agent_runtime() or {}
    return str(runtime.get("sessionId") or "").strip()


def _approved_plan_path(session_id: str) -> Path:
    safe = _safe_plan_id(session_id)
    return _workspace_root() / ".vibelution" / "plans" / f"plan-{safe}.md"


def enter_plan_mode_tool() -> str:
    """Switch the current session into plan mode. Writes stay blocked until exit."""

    from core.web.services.session.collaboration_mode import (
        CollaborationModeError,
        enter_session_plan_mode,
    )

    session_id = _current_session_id()
    if not session_id:
        return json.dumps(
            {"status": "error", "code": "NO_SESSION", "message": "当前没有可切换模式的会话。"},
            ensure_ascii=False,
        )
    try:
        transition = enter_session_plan_mode(session_id)
    except CollaborationModeError as exc:
        return json.dumps(
            {"status": "error", "code": "PLAN_MODE_REJECTED", "message": str(exc)},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "status": "ok",
            "message": "已进入计划模式。现在只查看代码并写出实现计划，不要改文件。",
            "mode": transition["mode"],
            "previousMode": transition["previousMode"],
            "planEnabled": True,
            "previousPlanEnabled": transition["previousPlanEnabled"],
        },
        ensure_ascii=False,
    )


def exit_plan_mode_tool(plan: str, allowed_prompts: Any = None) -> str:
    """Ask the user to approve the plan, save it, and leave plan mode."""

    from core.authorization.collaboration_mode import PLAN_MAX_CHARS, plan_is_enabled
    from core.web.services.session.collaboration_mode import (
        CollaborationModeError,
        exit_session_plan_mode,
        load_collaboration_state,
    )

    text = plan if isinstance(plan, str) else ""
    if not text.strip():
        return json.dumps(
            {"status": "error", "code": "INVALID_PLAN", "message": "退出计划需要一份计划正文。"},
            ensure_ascii=False,
        )
    if len(text) > PLAN_MAX_CHARS:
        return json.dumps(
            {
                "status": "error",
                "code": "INVALID_PLAN",
                "message": f"计划正文不能超过 {PLAN_MAX_CHARS} 字。",
            },
            ensure_ascii=False,
        )
    session_id = _current_session_id()
    if not session_id:
        return json.dumps(
            {"status": "error", "code": "NO_SESSION", "message": "当前没有可切换模式的会话。"},
            ensure_ascii=False,
        )
    if not plan_is_enabled(load_collaboration_state(session_id)):
        return json.dumps(
            {"status": "error", "code": "PLAN_MODE_REJECTED", "message": "当前不在计划模式，不能退出计划。"},
            ensure_ascii=False,
        )
    path = _approved_plan_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        transition = exit_session_plan_mode(session_id)
    except CollaborationModeError as exc:
        return json.dumps(
            {"status": "error", "code": "PLAN_MODE_REJECTED", "message": str(exc)},
            ensure_ascii=False,
        )
    prompts = allowed_prompts if isinstance(allowed_prompts, list) else []
    return json.dumps(
        {
            "status": "ok",
            "approved": True,
            "plan": text,
            "path": str(path),
            "mode": transition["mode"],
            "previousMode": transition["previousMode"],
            "planEnabled": False,
            "previousPlanEnabled": True,
            "allowedPrompts": prompts,
        },
        ensure_ascii=False,
    )


__all__ = ["plan_update_tool", "enter_plan_mode_tool", "exit_plan_mode_tool"]
