"""ConversationStore adapters for session list/create/rename/preview.

List and pagination read SQLite. Transcripts stay in the turn journal.
Callers must not wait on SQLite futures while holding ``_CHAT_STATE_LOCK``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from core.chat.conversation_store import parse_directory_cursor
from core.web.services.agent_config_authority import canonical_agent_config_payload

from . import directory_runtime


logger = logging.getLogger(__name__)

_DIRECTORY_LIST_PAGE = 200
_SYNC_TIMEOUT_SECONDS = 5.0


def _service():
    from core.web.services import session_service

    return session_service


def is_live() -> bool:
    return directory_runtime.is_directory_store_open()


def _empty_query_payload() -> dict[str, Any]:
    return {"items": [], "nextCursor": "", "totalEstimate": 0}


def query_session_summaries(
    *,
    limit: int = 50,
    cursor: str = "",
    q: str = "",
    agent_id: str = "",
    session_kind: str = "",
    state: str = "",
    sort: str = "updatedAt_desc",
) -> dict[str, Any] | None:
    if directory_runtime.wait_for_directory_startup() == "starting":
        return _empty_query_payload()
    store = directory_runtime.get_open_directory_store()
    if store is None:
        return None
    s = _service()
    normalized_limit = s._coerce_session_query_limit(limit)
    normalized_query = str(q or "").strip()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_kind = str(session_kind or "").strip().lower()
    normalized_state = str(state or "").strip().lower()
    normalized_sort = s._normalize_session_query_sort(sort)
    agent_by_id = s._agent_lookup_for_conversations()
    matching_agent_ids: tuple[str, ...] = ()
    if normalized_query and not normalized_agent_id:
        needle = normalized_query.lower()
        matching_agent_ids = tuple(
            str(item.get("agentId") or "").strip()
            for item in agent_by_id.values()
            if needle
            and needle in " ".join(
                (
                    str(item.get("displayName") or ""),
                    str(item.get("agentCode") or ""),
                    str(item.get("agentId") or ""),
                )
            ).lower()
        )
    include_hidden = bool(normalized_agent_id)
    before = parse_directory_cursor(cursor)
    if normalized_sort != "updatedAt_desc":
        page = store.repository.list_directory_page(
            agent_id=normalized_agent_id,
            session_kind=normalized_session_kind,
            status=normalized_state,
            query=normalized_query,
            include_hidden=include_hidden,
            matching_agent_ids=matching_agent_ids,
            limit=_DIRECTORY_LIST_PAGE,
        )
        summaries = [
            _summary_from_directory_row(row, agent_by_id=agent_by_id)
            for row in page["rows"]
        ]
        summaries.sort(
            key=s._session_query_sort_key(normalized_sort),
            reverse=normalized_sort.endswith("_desc"),
        )
        start = 0
        offset_cursor = s._coerce_nonnegative_int(cursor)
        start = min(offset_cursor, len(summaries))
        end = min(start + normalized_limit, len(summaries))
        items = summaries[start:end]
        return {
            "items": items,
            "nextCursor": str(end) if end < len(summaries) else "",
            "totalEstimate": len(summaries),
        }
    page = store.repository.list_directory_page(
        agent_id=normalized_agent_id,
        session_kind=normalized_session_kind,
        status=normalized_state,
        query=normalized_query,
        include_hidden=include_hidden,
        matching_agent_ids=matching_agent_ids,
        limit=normalized_limit,
        before=before,
    )
    items = [
        _summary_from_directory_row(row, agent_by_id=agent_by_id)
        for row in page["rows"]
    ]
    return {
        "items": items,
        "nextCursor": str(page.get("nextCursor") or ""),
        "totalEstimate": int(page.get("total") or 0),
    }


def list_session_summaries(*, include_hidden: bool = False) -> list[dict[str, Any]] | None:
    if directory_runtime.wait_for_directory_startup() == "starting":
        return []
    store = directory_runtime.get_open_directory_store()
    if store is None:
        return None
    s = _service()
    agent_by_id = s._agent_lookup_for_conversations()
    rows: list[dict[str, Any]] = []
    before: tuple[int, str] | None = None
    while True:
        page = store.repository.list_directory_page(
            include_hidden=include_hidden,
            limit=_DIRECTORY_LIST_PAGE,
            before=before,
        )
        batch = list(page.get("rows") or [])
        rows.extend(batch)
        next_cursor = str(page.get("nextCursor") or "")
        if not batch or not next_cursor:
            break
        before = parse_directory_cursor(next_cursor)
        if before is None:
            break
    summaries = [
        _summary_from_directory_row(row, agent_by_id=agent_by_id)
        for row in rows
    ]
    active_id = ""
    try:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        active_id = str(payload.get("active_conversation_id") or "").strip()
    except Exception:
        active_id = ""
    summaries.sort(
        key=lambda item: (
            0 if str(item.get("id") or "").strip() == active_id else 1,
            -s._timestamp_sort_key(item.get("updatedAt") or item.get("lastActive") or ""),
        )
    )
    return summaries


def sync_conversation_record(
    conversation: Mapping[str, Any] | None,
    *,
    last_preview: str = "",
    status: str = "",
    wait: bool = True,
) -> None:
    store = directory_runtime.get_open_directory_store()
    if store is None or not isinstance(conversation, Mapping):
        return
    session_id = str(
        conversation.get("conversation_id") or conversation.get("id") or ""
    ).strip()
    agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    if not session_id or not agent_id:
        return
    try:
        revision_id = _ensure_agent_revision(store, agent_id)
        future = store.repository.upsert_directory_session(
            session_id=session_id,
            agent_id=agent_id,
            agent_config_revision_id=revision_id,
            title=_conversation_title(conversation),
            parent_session_id=str(
                conversation.get("parent_session_id") or conversation.get("parentSessionId") or ""
            ).strip()
            or None,
            status=str(status or conversation.get("status") or "ready").strip() or "ready",
            session_kind=str(
                conversation.get("session_kind") or conversation.get("sessionKind") or "main"
            ).strip()
            or "main",
            session_role=str(
                conversation.get("session_role") or conversation.get("sessionRole") or ""
            ).strip(),
            conversation_index_kind=str(
                conversation.get("conversation_index_kind")
                or conversation.get("conversationIndexKind")
                or ""
            ).strip(),
            conversation_index_visibility=str(
                conversation.get("conversation_index_visibility")
                or conversation.get("conversationIndexVisibility")
                or ""
            ).strip(),
            hidden_from_index=bool(
                conversation.get("hidden_from_index") or conversation.get("hiddenFromIndex")
            ),
            team_id=str(conversation.get("team_id") or conversation.get("teamId") or "").strip(),
            last_preview=str(last_preview or ""),
        )
        if wait:
            future.result(timeout=_SYNC_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning(
            "Session directory upsert failed (%s).",
            type(exc).__name__,
        )


def sync_conversation_records(
    conversations: list[Mapping[str, Any] | None],
    *,
    last_preview: str = "",
    status: str = "",
    wait: bool = True,
) -> None:
    for conversation in conversations:
        sync_conversation_record(
            conversation,
            last_preview=last_preview,
            status=status,
            wait=wait,
        )


def touch_directory_session_safe(
    session_id: str,
    *,
    status: str = "",
    last_preview: str | None = None,
    title: str | None = None,
    wait: bool = False,
) -> None:
    store = directory_runtime.get_open_directory_store()
    if store is None:
        return
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    try:
        future = store.repository.touch_directory_session(
            session_id=normalized,
            status=status,
            last_preview=last_preview,
            title=title,
        )
        if wait:
            future.result(timeout=_SYNC_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning(
            "Session directory touch failed (%s).",
            type(exc).__name__,
        )


def archive_directory_session_safe(session_id: str, *, wait: bool = True) -> None:
    store = directory_runtime.get_open_directory_store()
    if store is None:
        return
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    try:
        future = store.repository.archive_directory_session(normalized)
        if wait:
            future.result(timeout=_SYNC_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning(
            "Session directory archive failed (%s).",
            type(exc).__name__,
        )


def _ensure_agent_revision(store: Any, agent_id: str) -> str:
    existing = store.repository.get_agent(agent_id)
    current = str((existing or {}).get("currentConfigRevisionId") or "").strip()
    if current:
        return current
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not isinstance(agent, dict):
        raise ValueError("Session directory record requires a live Agent snapshot.")
    snapshots = store.repository.import_agent_config_snapshots(
        [
            {
                "agent_id": agent_id,
                "display_name": str(agent.get("displayName") or agent_id).strip() or agent_id,
                "kind": str(agent.get("kind") or "assistant").strip() or "assistant",
                "status": str(agent.get("status") or "active").strip() or "active",
                "config": canonical_agent_config_payload(agent),
                "source": "session_directory_runtime",
            }
        ]
    ).result(timeout=_SYNC_TIMEOUT_SECONDS)
    if not snapshots:
        raise ValueError("Session directory Agent snapshot import returned no revision.")
    return str(snapshots[0]["configRevisionId"])


def _conversation_title(conversation: Mapping[str, Any]) -> str:
    return str(
        conversation.get("title")
        or conversation.get("task_title")
        or conversation.get("taskTitle")
        or ""
    ).strip()


def _iso_from_ms(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000).isoformat(timespec="seconds")


def _summary_from_directory_row(
    row: Mapping[str, Any],
    *,
    agent_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    s = _service()
    session_id = str(row.get("sessionId") or "").strip()
    agent_id = str(row.get("agentId") or "").strip()
    agent = agent_by_id.get(agent_id) if agent_id else None
    if not isinstance(agent, dict) and agent_id:
        loaded = s.get_agent(agent_id, include_archived=True)
        agent = loaded if isinstance(loaded, dict) else None
    stored_status = str(row.get("status") or "ready").strip() or "ready"
    phase_source = {
        "id": session_id,
        "last_turn_status": stored_status,
        "status": stored_status,
        "_hasLedgerMessages": bool(str(row.get("lastPreview") or "").strip()),
    }
    status = s._conversation_phase(session_id, phase_source)
    updated_at = _iso_from_ms(row.get("recencyAtMs") or row.get("updatedAtMs"))
    preview = str(row.get("lastPreview") or "").strip()
    raw_title = str(row.get("title") or "").strip()
    session_kind = str(row.get("sessionKind") or "main").strip() or "main"
    agent_display_name = str((agent or {}).get("displayName") or "").strip()
    if session_kind == "child" or not s._is_default_empty_session_title(raw_title):
        display_title = raw_title
    elif agent_id:
        display_title = agent_display_name or raw_title
    else:
        display_title = raw_title
    parent_session_id = str(row.get("parentSessionId") or "").strip()
    child_session_ids = list(row.get("childSessionIds") or [])
    agent_status = s._session_agent_status_payload(
        agent_id,
        agent if isinstance(agent, dict) else None,
        hydrate_agent=False,
        agent_lookup_checked=True,
        persisted_status_code="",
    )
    return {
        "id": session_id,
        "title": display_title or raw_title,
        "agentId": agent_id,
        "agentCode": str((agent or {}).get("agentCode") or "").strip(),
        "agentDisplayName": agent_display_name or display_title or raw_title,
        "agentAvatarImagePath": str((agent or {}).get("avatarImagePath") or "").strip(),
        "agentAvatarImageUrl": str((agent or {}).get("avatarImageUrl") or "").strip(),
        "agentPrimaryMode": str((agent or {}).get("primaryMode") or "").strip(),
        "agentRoleKey": str((agent or {}).get("roleKey") or "").strip(),
        "agentPromptTemplateId": str((agent or {}).get("promptTemplateId") or "").strip(),
        "agentPromptSnapshot": {},
        "lastPromptAssembly": {},
        "experimentBinding": None,
        "agentInboxPendingCount": s._agent_inbox_pending_count_for_summary(agent)
        if isinstance(agent, dict)
        else 0,
        "agentMissingId": "",
        "agentDirectSessionMismatch": False,
        "agentPrimaryDirectSessionId": str((agent or {}).get("directSessionId") or "").strip(),
        "sessionRole": str(row.get("sessionRole") or "").strip(),
        "dialogueModelId": s.agent_dialogue_model_id(agent) if isinstance(agent, dict) else "",
        "reasoningEffort": "",
        "workspacePath": s._session_workspace_relative_path(session_id),
        "agentWorkspacePath": str((agent or {}).get("workspacePath") or "").strip(),
        **agent_status,
        "status": status,
        "taskSummary": preview,
        "lastActive": updated_at,
        "updatedAt": updated_at,
        "currentPhase": status,
        "sessionKind": session_kind,
        "hiddenFromIndex": bool(row.get("hiddenFromIndex")),
        "readOnly": False,
        "archiveState": {},
        "conversationIndexVisibility": str(row.get("conversationIndexVisibility") or "").strip(),
        "conversationIndexKind": str(row.get("conversationIndexKind") or "").strip(),
        "conversationIndexErrors": [],
        "teamId": str(row.get("teamId") or "").strip(),
        "teamName": str((agent or {}).get("teamName") or "").strip(),
        "parentSessionId": parent_session_id,
        "rootSessionId": parent_session_id or session_id,
        "childSessionIds": child_session_ids,
        "activeChildSessionId": "",
        "childStatus": status,
        "taskTitle": raw_title,
        "resultCard": {},
        "sourceRef": s._source_authority_ref("session", session_id),
        "projectionEdit": s._projection_edit_contract("session", session_id),
        "agentSourceRef": s._source_authority_ref("agent", agent_id) if agent_id else None,
    }
