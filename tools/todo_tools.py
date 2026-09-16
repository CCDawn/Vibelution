# -*- coding: utf-8 -*-
"""Claude Code-style TodoWrite checklist tool.

The tool is presentation-only: it validates one full checklist snapshot and
returns a confirmation echo. No server-side state is kept — the conversation
surface derives the checklist from the journaled tool-call arguments, so the
journal remains the single source of truth and replay works for history turns.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List


VALID_TODO_STATUSES = ("pending", "in_progress", "completed")
MAX_TODO_ITEMS = 50


def _coerce_todo_items(todos: Any) -> tuple[List[Dict[str, str]], str]:
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError as exc:
            return [], f"todos 不是有效 JSON：{exc}"
    if not isinstance(todos, list):
        return [], "todos 需要是完整快照列表，每项包含 content、activeForm 和 status。"
    if len(todos) > MAX_TODO_ITEMS:
        return [], f"todos 一次最多 {MAX_TODO_ITEMS} 项，请拆分或合并条目。"

    normalized: List[Dict[str, str]] = []
    for index, item in enumerate(todos, start=1):
        if not isinstance(item, dict):
            return [], f"todos 第 {index} 项不是对象。"
        content = str(item.get("content") or "").strip()
        # Claude Code paradigm: content is the imperative form; activeForm is
        # the present-continuous form shown while the item runs. Tolerate a
        # missing activeForm by falling back to content, but never an empty
        # imperative line.
        active_form = str(item.get("activeForm") or "").strip() or content
        status = str(item.get("status") or "").strip().lower()
        if not content:
            return [], f"todos 第 {index} 项缺少 content。"
        if status not in VALID_TODO_STATUSES:
            return [], (
                f"todos 第 {index} 项 status 无效：{status or '空'}。"
                "可用状态：pending, in_progress, completed。"
            )
        normalized.append({"content": content, "activeForm": active_form, "status": status})

    in_progress_items = [item for item in normalized if item["status"] == "in_progress"]
    if len(in_progress_items) > 1:
        return [], "同一份清单最多只能有一个 in_progress 项；请先完成当前项再开始下一项。"
    return normalized, ""


def todo_write(todos: Any) -> str:
    """Write the full todo checklist snapshot for the current turn.

    Returns a confirmation echo; the conversation UI derives the checklist
    card from this journaled tool call, so always send the complete list
    (replacement semantics, not a delta).
    """
    normalized, error = _coerce_todo_items(todos)
    if error:
        return json.dumps(
            {
                "status": "error",
                "code": "INVALID_TODOS",
                "message": error,
                "example": {
                    "todos": [
                        {"content": "定位 owning surface", "activeForm": "定位 owning surface", "status": "completed"},
                        {"content": "补齐回归测试", "activeForm": "正在补齐回归测试", "status": "in_progress"},
                        {"content": "更新文档", "activeForm": "正在更新文档", "status": "pending"},
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )

    completed_count = sum(1 for item in normalized if item["status"] == "completed")
    in_progress = [item for item in normalized if item["status"] == "in_progress"]
    pending_count = sum(1 for item in normalized if item["status"] == "pending")
    return json.dumps(
        {
            "status": "ok",
            "itemCount": len(normalized),
            "completedCount": completed_count,
            "pendingCount": pending_count,
            "inProgress": [item["activeForm"] for item in in_progress],
            "message": "清单快照已记录。请保持恰好一个 in_progress，完成一项立即更新快照。",
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = ["todo_write", "VALID_TODO_STATUSES", "MAX_TODO_ITEMS"]
