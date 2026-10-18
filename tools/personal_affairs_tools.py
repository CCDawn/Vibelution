"""Agent-scoped personal affairs tools for the personal assistant.

The current Agent identity always comes from the server-owned runtime
context, so the assistant can only manage its own user's ledger. No tool
accepts an arbitrary target Agent id.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


def _runtime_context() -> dict[str, Any]:
    from core.web.services import agent_directory_service

    runtime = agent_directory_service.current_agent_runtime()
    return dict(runtime) if isinstance(runtime, dict) else {}


def _service():
    from core.web.services.personal_affairs_service import (
        get_personal_affairs_service,
    )

    return get_personal_affairs_service()


def _result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _blocked(message: str, *, error: str) -> str:
    return _result({"ok": False, "status": "blocked", "error": error, "message": message})


def personal_affairs_tool(
    action: str = "list",
    title: str = "",
    item_id: str = "",
    kind: str = "todo",
    note: str = "",
    due_at: str = "",
    status: str = "",
    source_turn_id: str = "",
) -> str:
    """管理当前用户的个人事务：待办、日程与目标。

    action: list 列表（可用 kind 过滤 todo/schedule/goal、status 过滤 open/done/cancelled）；
    add 新增（需 title，kind 默认 todo，可带 note 与 due_at ISO 时间）；
    complete 完成；cancel 取消；reopen 重新打开；set_due 修改截止时间（需 due_at）。
    完成与取消需 item_id。新增成功返回完整条目；列表返回 items 与 counts。
    """

    runtime = _runtime_context()
    runtime_agent_id = str(runtime.get("agentId") or "").strip()
    if not runtime_agent_id:
        return _blocked(
            "个人事务工具需要在已绑定 Agent 的运行时中调用。",
            error="agent_runtime_missing",
        )
    normalized_action = str(action or "").strip().lower()
    try:
        if normalized_action == "list":
            payload = {
                "ok": True,
                "status": "ready",
                "affairs": _service().list_items(
                    runtime_agent_id,
                    kind=str(kind or "").strip().lower(),
                    status=str(status or "").strip().lower(),
                ),
            }
        elif normalized_action == "add":
            payload = {
                "ok": True,
                "status": "ready",
                "item": _service().add_item(
                    runtime_agent_id,
                    kind=kind,
                    title=title,
                    note=note,
                    due_at=due_at,
                    source_turn_id=source_turn_id,
                ),
            }
        elif normalized_action in {"complete", "cancel", "reopen"}:
            if not str(item_id or "").strip():
                return _blocked("该操作需要 item_id。", error="item_id_required")
            method = {
                "complete": "complete_item",
                "cancel": "cancel_item",
                "reopen": "reopen_item",
            }[normalized_action]
            payload = {
                "ok": True,
                "status": "ready",
                "item": getattr(_service(), method)(
                    runtime_agent_id, item_id=str(item_id).strip()
                ),
            }
        elif normalized_action == "set_due":
            if not str(item_id or "").strip():
                return _blocked("该操作需要 item_id。", error="item_id_required")
            payload = {
                "ok": True,
                "status": "ready",
                "item": _service().set_due(
                    runtime_agent_id,
                    item_id=str(item_id).strip(),
                    due_at=due_at,
                ),
            }
        else:
            return _blocked(
                f"未知的个人事务操作：{action}",
                error="unknown_action",
            )
    except ValueError as exc:
        return _result(
            {
                "ok": False,
                "status": "rejected",
                "error": "affairs_contract_violation",
                "message": trim_lines(str(exc), max_lines=6),
            }
        )
    except Exception as exc:  # noqa: BLE001 - tool surface must stay JSON
        return _result(
            {
                "ok": False,
                "status": "failed",
                "error": "affairs_runtime_failure",
                "message": trim_lines(f"{type(exc).__name__}: {exc}", max_lines=4),
            }
        )
    return _result(payload)
