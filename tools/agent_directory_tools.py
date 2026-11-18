"""Agent directory tool: find another agent and the session it lives in.

The web API already exposes agents and sessions as two independent lists, which
means an agent that only has tool access cannot discover its peers without
knowing a session id in advance. This tool joins the two projections on
``agentId`` and returns one directory entry per agent, so discovery and delivery
can be planned from a single read.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["agent_directory_tool"]

_MAX_AGENTS = 50
_MAX_SESSIONS_PER_AGENT = 10


def _text(value: Any) -> str:
    return str(value or "").strip()


def _session_id(row: dict[str, Any]) -> str:
    return _text(row.get("sessionId")) or _text(row.get("id"))


def _session_title(row: dict[str, Any]) -> str:
    return (
        _text(row.get("title"))
        or _text(row.get("subject"))
        or _text(row.get("summary"))
        or _text(row.get("lastUserMessagePreview"))
    )


def _session_sort_key(row: dict[str, Any]) -> str:
    return _text(row.get("updatedAt")) or _text(row.get("lastActive")) or _text(row.get("createdAt"))


def _agent_entry(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "agentId": _text(agent.get("agentId")),
        "agentCode": _text(agent.get("agentCode")),
        "displayName": _text(agent.get("displayName")),
        "status": _text(agent.get("status")),
        "roleKey": _text(agent.get("roleKey")),
        "primaryMode": _text(agent.get("primaryMode")),
        "directSessionId": _text(agent.get("directSessionId")),
        "inboxPendingCount": int(agent.get("agentInboxPendingCount") or 0),
        "sessions": [],
    }


def _matches(entry: dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    for key in ("agentId", "agentCode", "displayName", "roleKey"):
        if needle in _text(entry.get(key)).lower():
            return True
    return False


def _load_agents() -> list[dict[str, Any]]:
    from core.web.services.agent_directory.projections import list_agents

    return [
        item
        for item in list_agents(include_archived=False, detail="summary")
        if isinstance(item, dict)
    ]


def _load_sessions() -> list[dict[str, Any]] | None:
    """Return session summaries, or ``None`` while the index is still starting."""

    from core.web.services.session.directory_bridge import list_session_summaries

    rows = list_session_summaries(include_hidden=False)
    if rows is None:
        return None
    return [row for row in rows if isinstance(row, dict)]


def _group_sessions(
    sessions: list[dict[str, Any]],
    *,
    sessions_per_agent: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(sessions, key=_session_sort_key, reverse=True):
        agent_id = _text(row.get("agentId"))
        if not agent_id:
            continue
        bucket = grouped.setdefault(agent_id, [])
        if len(bucket) >= sessions_per_agent:
            continue
        session_id = _session_id(row)
        if not session_id:
            continue
        bucket.append(
            {
                "sessionId": session_id,
                "title": _session_title(row),
                "lastTurnStatus": _text(row.get("lastTurnStatus")),
                "currentPhase": _text(row.get("currentPhase")),
                "lastActive": _text(row.get("lastActive")),
                "updatedAt": _text(row.get("updatedAt")),
                "parentSessionId": _text(row.get("parentSessionId")),
            }
        )
    return grouped


def agent_directory_tool(
    query: str = "",
    include_sessions: bool = True,
    limit: int = 20,
    sessions_per_agent: int = 3,
) -> str:
    """
    列出可发现的 Agent 及其对应会话，用于找到该联系谁、发到哪个会话。

    只读：不会发送消息、不会修改任何 Agent 或会话状态。发送请另行使用
    agent_message_tool，并把这里返回的 directSessionId 或 sessions[].sessionId
    作为 target_session。

    Args:
        query: 可选过滤词，匹配 agentId / agentCode / displayName / roleKey（不区分大小写）。
        include_sessions: 是否附带每个 Agent 最近的会话（默认 True）。
        limit: 最多返回多少个 Agent，1-50，默认 20。
        sessions_per_agent: 每个 Agent 最多附带几个会话，0-10，默认 3。

    Returns:
        JSON 字符串，含 ok、totalAgents、returned、sessionsAvailable 和 agents 列表；
        每个 Agent 带 agentId、agentCode、displayName、status、directSessionId、
        inboxPendingCount，以及可选的 sessions（sessionId、title、lastTurnStatus、
        currentPhase、lastActive、updatedAt、parentSessionId）。
    """

    try:
        bounded_limit = max(1, min(int(limit), _MAX_AGENTS))
    except (TypeError, ValueError):
        bounded_limit = 20
    try:
        bounded_sessions = max(0, min(int(sessions_per_agent), _MAX_SESSIONS_PER_AGENT))
    except (TypeError, ValueError):
        bounded_sessions = 3
    needle = _text(query).lower()

    try:
        agents = _load_agents()
    except Exception as exc:  # noqa: BLE001 - a discovery tool must report, not raise
        return json.dumps(
            {"ok": False, "error": f"agent_directory_unavailable: {type(exc).__name__}: {exc}"},
            ensure_ascii=False,
        )

    entries = [_agent_entry(agent) for agent in agents]
    entries = [entry for entry in entries if entry["agentId"] or entry["agentCode"]]
    filtered = [entry for entry in entries if _matches(entry, needle)]

    sessions_available = False
    if include_sessions and bounded_sessions > 0:
        try:
            sessions = _load_sessions()
        except Exception:  # noqa: BLE001 - the directory still works without sessions
            sessions = None
        if sessions is not None:
            sessions_available = True
            grouped = _group_sessions(sessions, sessions_per_agent=bounded_sessions)
            for entry in filtered:
                entry["sessions"] = grouped.get(entry["agentId"], [])

    selected = filtered[:bounded_limit]
    return json.dumps(
        {
            "ok": True,
            "totalAgents": len(entries),
            "matchedAgents": len(filtered),
            "returned": len(selected),
            "sessionsAvailable": sessions_available,
            "agents": selected,
        },
        ensure_ascii=False,
    )
