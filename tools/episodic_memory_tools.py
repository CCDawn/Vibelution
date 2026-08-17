# -*- coding: utf-8 -*-
"""Current-Agent private personal-memory write tools.

Hot path: append JSONL via agent_directory. No LLM extraction, no public lift,
and no write to another Agent's memory. This is not generation-handoff memory.
"""

from __future__ import annotations

import json
from typing import Any

from core.chat.chat_task_types import trim_lines

APPEND_PERSONAL_MEMORY_TOOL_NAME = "append_personal_memory_tool"
SUPERSEDE_PERSONAL_MEMORY_TOOL_NAME = "supersede_personal_memory_tool"
# Legacy LLM-facing names kept as callable aliases for tests/imports.
APPEND_EPISODIC_MEMORY_TOOL_NAME = APPEND_PERSONAL_MEMORY_TOOL_NAME
SUPERSEDE_EPISODIC_MEMORY_TOOL_NAME = SUPERSEDE_PERSONAL_MEMORY_TOOL_NAME


def append_personal_memory_tool(
    text: str,
    kind: str = "note",
    refs_json: str = "",
    occurred_at: str = "",
) -> str:
    """
    Append one private personal memory for the current Agent.

    Read the 个人记忆 section in the current turn context first. Do not use
    glob, grep, or cli_tool to find or open private memory files.
    Write only preferences, session facts, or private notes that should
    survive later sessions. This is not generation-handoff memory. Do not
    copy standards, skills, code, identity, or team/public knowledge.

    Args:
        text: Memory body (required).
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


def supersede_personal_memory_tool(
    episode_id: str,
    successor_text: str = "",
    kind: str = "note",
) -> str:
    """
    Invalidate one current private personal memory for the current Agent.

    Take episodeId from the 个人记忆 section in the current turn context; do
    not search memory files. Use this when a preference or fact is outdated.
    The original record stays; only validUntil is filled. Optional
    successor_text appends a replacement memory and links the old one to it.
    This is not generation-handoff memory.

    Args:
        episode_id: Current personal memory to supersede (required).
        successor_text: Optional replacement body. Empty means invalidate only.
        kind: Kind for the successor memory. Default note.

    Returns:
        JSON with ok/status and episode ids.
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
        normalized_episode_id = str(episode_id or "").strip()
        if not normalized_episode_id:
            return _json_result(
                {
                    "ok": False,
                    "status": "blocked",
                    "error": "episode_id_required",
                    "message": "作废个人记忆需要 episode_id。",
                }
            )
        successor_id = ""
        successor_kind = ""
        replacement = str(successor_text or "").strip()
        if replacement:
            refs = [{"type": "session", "id": session_id}] if session_id else []
            successor = ads.append_episodic_event(
                agent_id,
                kind=kind,
                text=replacement,
                refs=refs,
            )
            successor_id = str(successor.get("episodeId") or "")
            successor_kind = str(successor.get("kind") or "")
        event = ads.supersede_episodic_event(
            agent_id,
            normalized_episode_id,
            successor_episode_id=successor_id,
        )
        return _json_result(
            {
                "ok": True,
                "status": "superseded",
                "episodeId": str(event.get("episodeId") or normalized_episode_id),
                "agentId": str(event.get("agentId") or agent_id),
                "successorEpisodeId": successor_id,
                "successorKind": successor_kind,
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


append_episodic_memory_tool = append_personal_memory_tool
supersede_episodic_memory_tool = supersede_personal_memory_tool


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
