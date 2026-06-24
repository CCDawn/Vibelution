"""Canonical source authority metadata for Agent Kernel projections.

Projection surfaces may cache, index, filter, and link to facts, but they must
not become write owners for those facts. This module centralizes the source
authority contract so backend routes and frontend read models do not invent
parallel edit rules.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


SOURCE_AUTHORITY_VERSION = 1
ALLOWED_PROJECTION_ACTIONS = ("view", "link", "refresh", "repair")


_OWNER_BY_KIND = {
    "agent": "AgentDirectory",
    "agent_identity": "AgentDirectory",
    "agent_status": "AgentDirectory",
    "tool_policy": "AgentDirectory",
    "memory_policy": "AgentDirectory",
    "session": "ConversationLedger",
    "conversation": "ConversationLedger",
    "message": "ConversationLedger",
    "conversation_message": "ConversationLedger",
    "session_turn": "ConversationLedger",
    "room": "ChatRoomService",
    "chat_room": "ChatRoomService",
    "chat_room_round": "ChatRoomService",
    "task": "TaskLedger",
    "kernel_task": "TaskLedger",
    "team": "TeamWorkflow",
    "team_workflow": "TeamWorkflow",
}


def source_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a canonical source reference for one fact-bearing object."""

    normalized_kind = _normalize_kind(kind)
    normalized_id = str(source_id or "").strip()
    metadata = metadata if isinstance(metadata, dict) else {}
    owner = _OWNER_BY_KIND.get(normalized_kind, "unknown")
    route = _canonical_edit_route(normalized_kind, normalized_id, metadata)
    mutation_api = _canonical_mutation_api(normalized_kind, normalized_id, metadata)
    fact_authority = owner != "unknown" and bool(normalized_id)
    return {
        "kind": normalized_kind,
        "id": normalized_id,
        "owner": owner,
        "factAuthority": fact_authority,
        "canonicalEditRoute": route,
        "canonicalMutationApi": mutation_api,
        "projectionCanWrite": False,
        "allowedProjectionActions": list(ALLOWED_PROJECTION_ACTIONS),
        "sourceAuthorityVersion": SOURCE_AUTHORITY_VERSION,
    }


def projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the write contract a projection surface must follow."""

    ref = source_ref(kind, source_id, metadata)
    return {
        "canWrite": False,
        "mode": "deep_link_to_source",
        "reason": "projection_read_model",
        "sourceOwner": ref["owner"],
        "canonicalEditRoute": ref["canonicalEditRoute"],
        "canonicalMutationApi": ref["canonicalMutationApi"],
        "sourceAuthorityVersion": SOURCE_AUTHORITY_VERSION,
    }


def attach_source_ref(ref: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Enrich a projection ref with source authority and edit routing metadata."""

    payload = dict(ref) if isinstance(ref, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    kind = str(payload.get("kind") or "").strip()
    source_id = str(payload.get("id") or "").strip()
    source_metadata = {**metadata, **payload}
    source = source_ref(kind, source_id, source_metadata)
    edit = projection_edit_contract(kind, source_id, source_metadata)
    payload.update(
        {
            "sourceRef": source,
            "projectionEdit": edit,
            "sourceOwner": source["owner"],
            "canonicalEditRoute": source["canonicalEditRoute"],
            "projectionCanWrite": False,
        }
    )
    return payload


def _normalize_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower().replace("-", "_")
    if normalized == "inbox_message":
        return "message"
    return normalized


def _canonical_edit_route(kind: str, source_id: str, metadata: dict[str, Any]) -> str:
    normalized_id = str(source_id or "").strip()
    if not normalized_id:
        return ""
    if kind in {"agent", "agent_identity", "agent_status", "tool_policy", "memory_policy"}:
        agent_id = str(metadata.get("agentId") or normalized_id).strip()
        if kind == "tool_policy":
            return _route("/agents/tools", {"agent": agent_id})
        if kind == "memory_policy":
            return _route("/memory/agents", {"agentId": agent_id, "view": "agents"})
        return _route("/agents", {"agent": agent_id, "pane": "config"})
    if kind in {"session", "conversation"}:
        return _route("/chat", {"session": normalized_id})
    if kind in {"message", "conversation_message", "session_turn"}:
        session_id = str(
            metadata.get("sourceSessionId")
            or metadata.get("sessionId")
            or metadata.get("directSessionId")
            or ""
        ).strip()
        if session_id:
            return _route("/chat", {"session": session_id, "message": normalized_id})
        return ""
    if kind in {"room", "chat_room", "chat_room_round"}:
        room_id = str(metadata.get("sourceRoomId") or metadata.get("roomId") or normalized_id).strip()
        return _route("/chat", {"room": room_id})
    if kind in {"task", "kernel_task"}:
        return _route("/kernel", {"taskId": normalized_id})
    if kind in {"team", "team_workflow"}:
        return _route("/teams", {"team": normalized_id})
    return ""


def _canonical_mutation_api(kind: str, source_id: str, metadata: dict[str, Any]) -> str:
    normalized_id = str(source_id or "").strip()
    if not normalized_id:
        return ""
    if kind in {"agent", "agent_identity", "agent_status"}:
        agent_id = str(metadata.get("agentId") or normalized_id).strip()
        return f"/api/agents/{agent_id}"
    if kind == "tool_policy":
        agent_id = str(metadata.get("agentId") or normalized_id).strip()
        return f"/api/agents/{agent_id}"
    if kind == "memory_policy":
        agent_id = str(metadata.get("agentId") or normalized_id).strip()
        return f"/api/agents/{agent_id}"
    if kind in {"session", "conversation"}:
        return f"/api/sessions/{normalized_id}"
    if kind in {"message", "conversation_message", "session_turn"}:
        session_id = str(metadata.get("sourceSessionId") or metadata.get("sessionId") or "").strip()
        return f"/api/sessions/{session_id}/messages" if session_id else ""
    if kind in {"room", "chat_room", "chat_room_round"}:
        room_id = str(metadata.get("sourceRoomId") or metadata.get("roomId") or normalized_id).strip()
        return f"/api/chat-rooms/{room_id}"
    if kind in {"task", "kernel_task"}:
        return f"/api/kernel/tasks/{normalized_id}"
    if kind in {"team", "team_workflow"}:
        return f"/api/teams/{normalized_id}"
    return ""


def _route(path: str, params: dict[str, str]) -> str:
    filtered = {key: value for key, value in params.items() if str(value or "").strip()}
    query = urlencode(filtered)
    return f"{path}?{query}" if query else path
