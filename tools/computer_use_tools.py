# -*- coding: utf-8 -*-
"""Agent tool bridge for controlled Computer Use automation."""

from __future__ import annotations

import json
from typing import Any


def computer_use_task_tool(
    task: str,
    target_url: str = "",
    allowed_domains: str = "",
    actions: str = "",
    max_steps: int = 20,
    require_confirmation: bool = True,
    mode: str = "browser",
) -> str:
    """Run a bounded Computer Use task in a sandbox browser session."""

    try:
        from core.web.services.computer_use_service import start_computer_use_task

        result = start_computer_use_task(
            task=task,
            target_url=target_url,
            allowed_domains=allowed_domains,
            actions=actions,
            max_steps=max_steps,
            require_confirmation=require_confirmation,
            mode=mode,
        )
    except Exception as exc:
        result: dict[str, Any] = {
            "status": "failed",
            "sessionId": "",
            "summary": "Computer Use task could not start.",
            "steps": [],
            "screenshotUrl": "",
            "needsConfirmation": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return json.dumps(result, ensure_ascii=False)


def computer_use_session_tool(
    session_id: str,
    action: str = "get",
    confirmation: str = "approved",
    reason: str = "cancelled_by_agent",
) -> str:
    """Read, confirm, or cancel a Computer Use sandbox browser session."""

    try:
        from core.web.services.computer_use_service import (
            cancel_computer_use_session,
            confirm_computer_use_session,
            get_computer_use_session,
        )

        normalized_action = str(action or "get").strip().lower() or "get"
        if normalized_action in {"get", "read", "status"}:
            result = get_computer_use_session(session_id)
        elif normalized_action in {"confirm", "approve", "continue"}:
            result = confirm_computer_use_session(session_id, confirmation=confirmation)
        elif normalized_action in {"cancel", "stop"}:
            result = cancel_computer_use_session(session_id, reason=reason)
        else:
            raise ValueError("action must be one of: get, confirm, cancel.")
    except Exception as exc:
        result: dict[str, Any] = {
            "status": "failed",
            "sessionId": str(session_id or ""),
            "summary": "Computer Use session operation failed.",
            "steps": [],
            "screenshotUrl": "",
            "needsConfirmation": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return json.dumps(result, ensure_ascii=False)
