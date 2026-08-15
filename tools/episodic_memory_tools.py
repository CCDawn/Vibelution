# -*- coding: utf-8 -*-
"""Current-Agent private episode write tool.

Hot path: append JSONL via agent_directory. No LLM extraction, no public lift,
and no write to another Agent's memory.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines

APPEND_EPISODIC_MEMORY_TOOL_NAME = "append_episodic_memory_tool"


def append_episodic_memory_tool(
    text: str,
    kind: str = "note",
    refs_json: str = "",
    occurred_at: str = "",
) -> str:
    """
    Append one private episode for the current Agent.

    Use this for preferences, session facts, or private notes that should survive
    later turns. Do not copy standards, skills, code, identity, or team/public
    knowledge here. This does not promote anything to the public catalog.

    Args:
        text: Episode body (required).
        kind: note | preference | session_fact | private_note. Default note.
        refs_json: Optional JSON list of {type, id} where type is
            session|path|card|item. Current session is attached automatically.
        occurred_at: Optional ISO timestamp for when the fact happened.

    Returns:
        JSON with ok/status and the stored episodeId.
    """
    try:
        from core.web.services import agent_directory_service as ads

        runtime = ads.current_agent_runtime()
        agent_id = str(runtime.get("agentId") or "").strip()
        session_id = str(runtime.get("sessionId") or "").strip()
        if not agent_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "agent_runtime_missing",
                    "message": "当前工具需要在已绑定 AgentInstance 的运行时中调用。",
                }
            )
        refs = _parse_refs(refs_json)
        if session_id and not any(
            item.get("type") == "session" and item.get("id") == session_id for item in refs
        ):
            refs.append({"type": "session", "id": session_id})
        event = ads.append_episodic_event(
            agent_id,
            kind=kind,
            text=text,
            refs=refs,
            occurred_at=occurred_at,
        )
        return _json_result(
            {
                "ok": True,
                "status": "appended",
                "episodeId": str(event.get("episodeId") or ""),
                "agentId": str(event.get("agentId") or agent_id),
                "kind": str(event.get("kind") or ""),
                "validUntil": str(event.get("validUntil") or ""),
            }
        )
    except Exception as exc:
        return _json_result(
            {
                "ok": False,
                "status": "failed",
                "error": type(exc).__name__,
                "message": trim_lines(str(exc), max_lines=2),
            }
        )


def _parse_refs(refs_json: str) -> list[dict[str, Any]]:
    raw = str(refs_json or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("refs_json must be a JSON list of {type, id} objects.")
    if not isinstance(payload, list):
        raise ValueError("refs_json must be a JSON list of {type, id} objects.")
    return [item for item in payload if isinstance(item, dict)]


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
