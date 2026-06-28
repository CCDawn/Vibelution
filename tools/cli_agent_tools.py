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
    action: str = "task",
    terminal_session_id: str = "",
    input_text: str = "",
) -> str:
    """Control a supported external CLI coding agent and return a bounded JSON result."""

    from core.web.services.cli_agent_service import run_cli_agent

    runtime = _current_runtime_source()
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
        source_session_id=str(runtime.get("sessionId") or ""),
        source_run_id=str(runtime.get("turnId") or ""),
        action=action,
        terminal_session_id=terminal_session_id,
        input_text=input_text,
    )
    return json.dumps(result, ensure_ascii=False)


def _current_runtime_source() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        return {}
    return runtime if isinstance(runtime, dict) else {}
