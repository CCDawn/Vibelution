# -*- coding: utf-8 -*-
"""Agent-facing tools for the external skills memory library."""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines


SKILL_LIBRARY_SEARCH_TOOL_NAME = "skill_library_search_tool"


def skill_library_search_tool(
    query: str = "",
    query_mode: str = "auto",
    source: str = "all_visible",
    scope: str = "all_visible",
    team_id: str = "",
    tags: str = "",
    limit: int = 8,
) -> str:
    """
    Search the external memory-backed skills library.

    The tool reads only the external workspace skills indexes. It does not fall
    back to .codex/skills or plugin cache directories. Results identify whether
    a skill is managed by Vibelution or only system-indexed and read-only.
    """

    runtime = _current_runtime()
    actor_agent_id = str(runtime.get("agentId") or "").strip()
    try:
        from core.web.services import skill_library_service

        payload = skill_library_service.search_skill_library(
            query=trim_lines(str(query or ""), max_lines=4).strip(),
            query_mode=query_mode,
            source=source,
            scope=scope,
            actor_agent_id=actor_agent_id,
            team_id=str(team_id or "").strip(),
            tags=_split_tags(tags),
            limit=limit,
        )
        _record_event(
            "skill_library.tool.search.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "queryMode": str((payload.get("request") or {}).get("effectiveQueryMode") or query_mode),
                "source": str((payload.get("request") or {}).get("source") or source),
                "scope": str((payload.get("request") or {}).get("scope") or scope),
                "resultCount": int((payload.get("summary") or {}).get("resultCount") or 0),
            },
        )
        return _json_result({"ok": True, "status": "succeeded", "actorAgentId": actor_agent_id, **payload})
    except Exception as exc:
        _record_event(
            "skill_library.tool.search.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__, "source": str(source or ""), "scope": str(scope or "")},
        )
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
                "actorAgentId": actor_agent_id,
            }
        )


def _split_tags(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()][:24]


def _current_runtime() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
        return runtime if isinstance(runtime, dict) else {}
    except Exception:
        return {}


def _record_event(
    event_code: str,
    *,
    runtime: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "skill_library",
            "tool",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(runtime.get("agentId") or "").strip(),
                "sessionId": str(runtime.get("sessionId") or "").strip(),
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
