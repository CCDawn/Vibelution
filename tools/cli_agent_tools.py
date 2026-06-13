"""LangChain-facing wrapper for controlled CLI agent execution."""

from __future__ import annotations

import json
from typing import Any


def cli_agent_run_tool(
    agent_type: str = "",
    task: str = "",
    cwd: str = "",
    mode: str = "readonly",
    timeout: int = 600,
    output_limit: int = 12000,
    model: str = "",
    agent: str = "",
    allow_unsafe_permissions: bool = False,
) -> str:
    """Run a supported external CLI coding agent and return a bounded JSON result."""

    from core.web.services.cli_agent_service import run_cli_agent

    result: dict[str, Any] = run_cli_agent(
        agent_type=agent_type,
        task=task,
        cwd=cwd,
        mode=mode,
        timeout=timeout,
        output_limit=output_limit,
        model=model,
        agent=agent,
        allow_unsafe_permissions=allow_unsafe_permissions,
    )
    return json.dumps(result, ensure_ascii=False)
