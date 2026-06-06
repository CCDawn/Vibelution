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
