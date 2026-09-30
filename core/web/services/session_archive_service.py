"""Session-level archive/unarchive (ZCode-style lightweight archive).

Archive is a pure metadata flip on the conversation row: ``archive_state``
(status ``archived`` + timestamp) plus the read-only/index-hidden flags the
Agent-archive path already uses. Session data files are never moved or
deleted, and the flip is fully reversible by ``unarchive``.

Index sync reuses the existing directory bridge:

- archive seals the directory row (``archived_at_ms``) and re-syncs it with
  ``hidden_from_index`` so default listings exclude it even if a later
  directory upsert resurrects the row;
- unarchive re-derives the conversation index kind/visibility from the owning
  Agent and upserts the directory row, which clears ``archived_at_ms`` and
  restores default visibility.

Messaging stays blocked on archived sessions through the existing
``_ensure_session_mutable`` guard, so no submit-path change is needed here.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ARCHIVE_SOURCE = "session_archive"
_BUSY_PHASES = {"queued", "running", "stopping", "paused"}


def _service():
    from core.web.services import session_service

    return session_service


def _conversation_archive_state(conversation: dict[str, Any]) -> dict[str, Any]:
    raw = conversation.get("archive_state") or conversation.get("archiveState")
    return dict(raw) if isinstance(raw, dict) else {}


def conversation_is_archived(conversation: dict[str, Any] | None) -> bool:
    """True when the conversation row carries an archived archive_state."""

    if not isinstance(conversation, dict):
        return False
    archive_state = _conversation_archive_state(conversation)
    return str(archive_state.get("status") or "").strip().lower() == "archived"


def _archive_state_source(conversation: dict[str, Any]) -> str:
    """Source discriminant of the archived flag ("" when absent)."""

    return str(_conversation_archive_state(conversation).get("source") or "").strip().lower()


def _response(session_id: str, conversation: dict[str, Any], *, changed: bool) -> dict[str, Any]:
    archive_state = _conversation_archive_state(conversation)
    return {
        "sessionId": session_id,
        "status": str(archive_state.get("status") or ""),
        "changed": changed,
        "archivedAt": str(archive_state.get("archivedAt") or ""),
        "readOnly": bool(conversation.get("read_only") or conversation.get("readOnly")),
    }


def _require_conversation(session_id: str) -> dict[str, Any]:
    s = _service()
    normalized = str(session_id or "").strip()
    if not normalized:
        raise s.SessionNotFoundError("Session id is required.")
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized)
    if conversation is None:
        raise s.SessionNotFoundError(f"Session not found: {normalized}")
    return conversation


def _apply_archive_flags(conversation: dict[str, Any], timestamp: str) -> None:
    s = _service()
    ads = s.agent_directory_service
    archive_state = {
        "status": "archived",
        "source": _ARCHIVE_SOURCE,
        "archivedAt": timestamp,
        # Snapshot of the index metadata this archive flip replaced, so
        # unarchive restores the exact previous visibility.
        "previousConversationIndexKind": str(
            conversation.get("conversation_index_kind")
            or conversation.get("conversationIndexKind")
            or ""
        ),
        "previousConversationIndexVisibility": str(
            conversation.get("conversation_index_visibility")
            or conversation.get("conversationIndexVisibility")
            or ""
        ),
        "previousConversationReadOnly": bool(
            conversation.get("read_only") or conversation.get("readOnly")
        ),
        "previousHiddenFromIndex": bool(
            conversation.get("hidden_from_index") or conversation.get("hiddenFromIndex")
        ),
    }
    conversation["archive_state"] = dict(archive_state)
    conversation["archiveState"] = dict(archive_state)
    conversation["read_only"] = True
    conversation["readOnly"] = True
    conversation["hidden_from_index"] = True
    conversation["hiddenFromIndex"] = True
    conversation["conversation_index_kind"] = ads.CONVERSATION_INDEX_KIND_HIDDEN
    conversation["conversationIndexKind"] = ads.CONVERSATION_INDEX_KIND_HIDDEN
    conversation["conversation_index_visibility"] = ads.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    conversation["conversationIndexVisibility"] = ads.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    conversation["updated_at"] = timestamp


def _clear_archive_flags(conversation: dict[str, Any], timestamp: str) -> None:
    s = _service()
    archive_state = _conversation_archive_state(conversation)
    previous_kind = str(archive_state.get("previousConversationIndexKind") or "")
    previous_visibility = str(archive_state.get("previousConversationIndexVisibility") or "")
    if not previous_kind:
        # Legacy row archived before snapshots existed: re-derive from the Agent.
        agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
        agent = s.get_agent(agent_id, include_archived=True) if agent_id else None
        classification = s._conversation_index_classification(conversation, agent)
        previous_kind = str(classification.get("kind") or "").strip()
        previous_visibility = s._conversation_index_visibility_for_classification(
            previous_kind,
            agent,
        )
    previous_hidden = bool(archive_state.get("previousHiddenFromIndex"))
    previous_read_only = bool(archive_state.get("previousConversationReadOnly"))
    conversation.pop("archive_state", None)
    conversation.pop("archiveState", None)
    conversation["read_only"] = previous_read_only
    conversation["readOnly"] = previous_read_only
    conversation["hidden_from_index"] = previous_hidden
    conversation["hiddenFromIndex"] = previous_hidden
    conversation["conversation_index_kind"] = previous_kind
    conversation["conversationIndexKind"] = previous_kind
    conversation["conversation_index_visibility"] = previous_visibility
    conversation["conversationIndexVisibility"] = previous_visibility
    conversation["updated_at"] = timestamp


def _sync_directory(conversation: dict[str, Any], *, archive: bool) -> None:
    s = _service()
    session_id = str(
        conversation.get("conversation_id") or conversation.get("id") or ""
    ).strip()
    from core.web.services.session import directory_bridge

    if archive:
        # Re-sync flags first (hidden_from_index derived from chat_state), then
        # seal the directory row (archived_at_ms). A later unrelated upsert may
        # clear archived_at_ms but keeps hidden_from_index until unarchive.
        directory_bridge.sync_conversation_record(conversation, touch_recency=False)
        directory_bridge.archive_directory_session_safe(session_id, wait=True)
    else:
        # Upsert clears archived_at_ms and re-derives hidden_from_index=False,
        # which restores default listing visibility.
        directory_bridge.sync_conversation_record(conversation, wait=True)
    s._invalidate_session_list_cache()


def archive_session(session_id: str) -> dict[str, Any]:
    """Archive one session: metadata flag + directory index seal. Idempotent."""

    s = _service()
    normalized = str(session_id or "").strip()
    timestamp = s._now_timestamp()
    with s._CHAT_STATE_LOCK:
        conversation = _require_conversation(normalized)
        if conversation_is_archived(conversation):
            return _response(normalized, conversation, changed=False)
        normalized_conversation = s._normalize_conversation(
            conversation,
            agent_by_id=s._agent_lookup_for_conversations(),
            ensure_workspace=False,
            lightweight=True,
        ) or {"id": normalized}
        phase = s._conversation_phase(normalized, normalized_conversation)
        if phase in _BUSY_PHASES:
            raise s.SessionBusyError(
                s.text_for(
                    s.get_web_language(),
                    zh=f"会话 {normalized} 仍在运行或停止中，暂时不能归档。",
                    en=f"Session {normalized} is still running or stopping; it cannot be archived yet.",
                )
            )
        _apply_archive_flags(conversation, timestamp)
        s.save_session_chat_state(s.PROJECT_ROOT, normalized, conversation)
    _sync_directory(conversation, archive=True)
    s._publish_session_detail_snapshot(normalized)
    s.record_runtime_scene_event(
        "conversation",
        "chat_state",
        "conversation.session_archive.archived",
        level="info",
        outcome="archived",
        message="Session archived (metadata flag only).",
        fields={"sessionId": normalized},
        lifecycle=True,
    )
    return _response(normalized, conversation, changed=True)


def unarchive_session(session_id: str) -> dict[str, Any]:
    """Unarchive one session previously archived through this service."""

    s = _service()
    normalized = str(session_id or "").strip()
    timestamp = s._now_timestamp()
    with s._CHAT_STATE_LOCK:
        conversation = _require_conversation(normalized)
        if not conversation_is_archived(conversation):
            return _response(normalized, conversation, changed=False)
        # Agent-archive seals sessions under source="agent_archive"; only the
        # Agent lifecycle may unseal them. User unarchive must not break the
        # "agent archived implies sessions sealed" invariant.
        if _archive_state_source(conversation) != _ARCHIVE_SOURCE:
            raise s.SessionValidationError(
                s.text_for(
                    s.get_web_language(),
                    zh=f"会话 {normalized} 随 Agent 归档封存，请通过恢复 Agent 解除封存。",
                    en=f"Session {normalized} was sealed by an Agent archive; restore the Agent to unseal it.",
                )
            )
        _clear_archive_flags(conversation, timestamp)
        s.save_session_chat_state(s.PROJECT_ROOT, normalized, conversation)
    _sync_directory(conversation, archive=False)
    s._publish_session_detail_snapshot(normalized)
    s.record_runtime_scene_event(
        "conversation",
        "chat_state",
        "conversation.session_archive.unarchived",
        level="info",
        outcome="restored",
        message="Session unarchived (metadata flag cleared).",
        fields={"sessionId": normalized},
        lifecycle=True,
    )
    return _response(normalized, conversation, changed=True)


def list_archived_sessions(
    *,
    limit: int = 200,
    cursor: str = "",
) -> dict[str, Any]:
    """Return one cursor-paginated page of archived session summaries.

    Mirrors the ``session_service.query_sessions`` envelope so the frontend can
    reuse the same row rendering. Archived rows are excluded from the canonical
    session list projection, so this reads the persisted chat-state rows
    directly (same source the Agent-archive lifecycle uses) and normalizes each
    with the shared lightweight projection.
    """

    s = _service()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations") if isinstance(payload, dict) else []
        if not isinstance(conversations, list):
            conversations = []
        archived_raw = [
            raw
            for raw in conversations
            if isinstance(raw, dict)
            and conversation_is_archived(raw)
            # Agent-sealed rows (source="agent_archive") belong to the Agent
            # lifecycle view, not the user's session archive.
            and _archive_state_source(raw) == _ARCHIVE_SOURCE
        ]
    agent_by_id = s._agent_lookup_for_conversations()
    archived = []
    for raw in archived_raw:
        session_id = str(raw.get("conversation_id") or raw.get("conversationId") or "").strip()
        normalized = s._normalize_conversation(
            raw,
            agent_by_id=agent_by_id,
            ensure_workspace=False,
            lightweight=True,
        ) or {"id": session_id}
        archived.append(normalized)
    archived.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    total = len(archived)
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = 200
    normalized_limit = max(1, min(200, limit_value if limit_value > 0 else 200))
    try:
        offset = int(str(cursor or "").strip() or "0")
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, min(offset, total))
    page = archived[offset : offset + normalized_limit]
    next_offset = offset + len(page)
    return {
        "items": page,
        "nextCursor": str(next_offset) if next_offset < total else "",
        "totalEstimate": total,
    }
