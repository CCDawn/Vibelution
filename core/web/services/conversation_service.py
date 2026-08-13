"""Unified conversation index for direct agents and group rooms."""

from __future__ import annotations

from typing import Any

from core.agent_kernel.source_authority import projection_edit_contract, source_ref

from . import chat_room_service, session_service, team_service
from .runtime_scene_service import record_runtime_scene_event


def list_conversations() -> list[dict[str, Any]]:
    """Return direct agent conversations and group rooms in one index."""

    items: list[dict[str, Any]] = []
    sessions = session_service.list_sessions()
    for session in sessions:
        items.append(
            {
                "conversationId": str(session.get("id") or "").strip(),
                "type": "direct_agent",
                "title": str(session.get("title") or session.get("agentDisplayName") or "").strip(),
                "agentId": str(session.get("agentId") or "").strip(),
                "agentCode": str(session.get("agentCode") or "").strip(),
                "agentDisplayName": str(session.get("agentDisplayName") or "").strip(),
                "agentAvatarImagePath": str(session.get("agentAvatarImagePath") or "").strip(),
                "agentAvatarImageUrl": str(session.get("agentAvatarImageUrl") or "").strip(),
                "directSessionId": str(session.get("id") or "").strip(),
                "roomId": "",
                "status": str(session.get("status") or "").strip(),
                "summary": str(session.get("taskSummary") or "").strip(),
                "updatedAt": str(session.get("updatedAt") or session.get("lastActive") or "").strip(),
                "workspacePath": str(session.get("agentWorkspacePath") or session.get("workspacePath") or "").strip(),
                "agentPrimaryMode": str(session.get("agentPrimaryMode") or "").strip(),
                "agentRoleKey": str(session.get("agentRoleKey") or "").strip(),
                "agentPromptTemplateId": str(session.get("agentPromptTemplateId") or "").strip(),
                "agentInboxPendingCount": int(session.get("agentInboxPendingCount") or 0),
                "conversationIndexVisibility": str(session.get("conversationIndexVisibility") or "user_visible").strip()
                or "user_visible",
                "conversationIndexKind": str(session.get("conversationIndexKind") or "").strip(),
                "conversationIndexErrors": _conversation_index_errors(session),
                "teamId": str(session.get("teamId") or "").strip(),
                "teamName": str(session.get("teamName") or "").strip(),
                "sourceRef": _dict_payload(session.get("sourceRef")),
                "projectionEdit": _dict_payload(session.get("projectionEdit")),
                "agentSourceRef": _optional_dict_payload(session.get("agentSourceRef")),
            }
        )
    group_items, filtered_archived_team_room_count = _list_group_conversations_with_count(
        sessions
    )
    items.extend(group_items)
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    _record_conversation_index_loaded(
        item_count=len(items),
        session_count=len(sessions),
        filtered_archived_team_room_count=filtered_archived_team_room_count,
    )
    return items


def list_group_conversations(
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project group rooms from an already loaded session page."""

    items, _filtered_count = _list_group_conversations_with_count(sessions)
    items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return items


def build_chat_workbench_bootstrap(
    *,
    limit: int = 50,
    cursor: str = "",
    q: str = "",
) -> dict[str, Any]:
    """Build the first-paint catalog with one agent and session projection pass."""

    from core.web.services.agent_directory_service import list_agents
    from core.web.services.session import directory_runtime

    agents = list_agents(include_archived=False, detail="summary")
    agent_by_id = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    session_page = session_service.query_sessions(
        limit=limit,
        cursor=cursor,
        q=q,
        agent_by_id=agent_by_id,
    )
    store = directory_runtime.get_open_directory_store()
    active_session_id = ""
    if store is not None:
        active_session_id, _bindings = store.repository.get_chat_state_directory_overlay()
    return {
        "activeSessionId": str(active_session_id or "").strip(),
        "sessionPage": session_page,
        "agents": agents,
        # Direct conversations are already represented by sessionPage. The
        # unified index needs only group rooms as its additional first-paint input.
        "conversations": list_group_conversations(list(session_page.get("items") or [])),
    }


def _list_group_conversations_with_count(
    sessions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    session_summaries = {
        str(session.get("id") or "").strip(): session
        for session in sessions
        if isinstance(session, dict) and str(session.get("id") or "").strip()
    }
    archived_team_room_ids = _archived_team_room_ids()
    items: list[dict[str, Any]] = []
    filtered_archived_team_room_count = 0
    for room in chat_room_service.list_chat_rooms_for_conversation_index(
        session_summaries=session_summaries
    ):
        room_id = str(room.get("roomId") or "").strip()
        if room_id in archived_team_room_ids:
            filtered_archived_team_room_count += 1
            continue
        room_source_ref = source_ref("chat_room", room_id, {"roomId": room_id})
        room_projection_edit = projection_edit_contract("chat_room", room_id, {"roomId": room_id})
        items.append(
            {
                "conversationId": room_id,
                "type": "group_room",
                "title": str(room.get("title") or room.get("roomId") or "").strip(),
                "agentId": "",
                "directSessionId": "",
                "roomId": room_id,
                "status": str(room.get("status") or "").strip(),
                "summary": str(room.get("summary") or "").strip(),
                "updatedAt": str(room.get("updatedAt") or "").strip(),
                "workspacePath": f"workspace/chat_rooms/{room.get('roomId') or ''}",
                "participantCount": len(list(room.get("participants") or [])),
                "mode": str(room.get("mode") or "").strip(),
                "sourceRef": room_source_ref,
                "projectionEdit": room_projection_edit,
                "agentSourceRef": None,
            }
        )
    return items, filtered_archived_team_room_count


def _archived_team_room_ids() -> set[str]:
    return team_service.list_archived_team_linked_chat_room_ids()


def _conversation_index_errors(session: dict[str, Any]) -> list[str]:
    raw_errors = session.get("conversationIndexErrors") or []
    if isinstance(raw_errors, list):
        return [str(item).strip() for item in raw_errors if str(item).strip()]
    return [str(raw_errors).strip()] if str(raw_errors).strip() else []


def _dict_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_dict_payload(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _record_conversation_index_loaded(
    *,
    item_count: int,
    session_count: int,
    filtered_archived_team_room_count: int,
) -> None:
    if filtered_archived_team_room_count <= 0:
        return
    try:
        record_runtime_scene_event(
            "conversation_service",
            "conversation_index",
            "conversation.index.filtered_archived_team_rooms",
            message="Conversation index filtered archived Team linked rooms.",
            outcome="observed",
            fields={
                "itemCount": item_count,
                "sessionCount": session_count,
                "filteredArchivedTeamRoomCount": filtered_archived_team_room_count,
            },
        )
    except Exception:
        pass
