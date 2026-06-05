#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tools for splitting one chat session into child task sessions."""

from __future__ import annotations

import json
from typing import Any


def _json_dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_text_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    return [str(item).strip() for item in data if str(item).strip()]
            except Exception:
                pass
        return [part.strip() for part in stripped.splitlines() if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _current_session_id(explicit_session_id: str = "") -> str:
    normalized = str(explicit_session_id or "").strip()
    if normalized:
        return normalized
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        runtime = {}
    return str((runtime or {}).get("sessionId") or "").strip()


def create_child_session_tool(
    user_request: str,
    task_title: str = "",
    split_reason: str = "",
    inherited_facts: Any = "",
    relevant_files: Any = "",
    relevant_logs: Any = "",
    constraints: Any = "",
    excluded_context_summary: str = "",
    auto_start: bool = True,
    switch_to_child: bool = True,
    parent_session_id: str = "",
) -> str:
    """Create a child session under the current chat session and optionally start it."""

    session_id = _current_session_id(parent_session_id)
    if not session_id:
        return _json_dump(
            {
                "status": "error",
                "error": "missing_session_id",
                "message": "当前 Agent runtime 没有可用 sessionId，无法创建子对话。",
            }
        )
    try:
        from core.web.services.session_service import create_child_session

        result = create_child_session(
            session_id,
            user_request=str(user_request or "").strip(),
            task_title=str(task_title or "").strip(),
            split_reason=str(split_reason or "").strip(),
            inherited_facts=_normalize_text_list(inherited_facts),
            relevant_files=_normalize_text_list(relevant_files),
            relevant_logs=_normalize_text_list(relevant_logs),
            constraints=_normalize_text_list(constraints),
            excluded_context_summary=str(excluded_context_summary or "").strip(),
            auto_start=bool(auto_start),
            switch_to_child=bool(switch_to_child),
            source="agent_tool_split",
        )
    except Exception as exc:
        return _json_dump(
            {
                "status": "error",
                "error": exc.__class__.__name__,
                "message": str(exc),
                "parentSessionId": session_id,
            }
        )
    return _json_dump(result)


def list_child_sessions_tool(parent_session_id: str = "") -> str:
    """List child sessions under the current root chat session."""

    session_id = _current_session_id(parent_session_id)
    if not session_id:
        return _json_dump(
            {
                "status": "error",
                "error": "missing_session_id",
                "message": "当前 Agent runtime 没有可用 sessionId，无法读取子对话。",
            }
        )
    try:
        from core.web.services.session_service import list_child_sessions

        children = list_child_sessions(session_id)
    except Exception as exc:
        return _json_dump(
            {
                "status": "error",
                "error": exc.__class__.__name__,
                "message": str(exc),
                "parentSessionId": session_id,
            }
        )
    return _json_dump(
        {
            "status": "ok",
            "parentSessionId": session_id,
            "childSessions": children,
            "count": len(children),
        }
    )
