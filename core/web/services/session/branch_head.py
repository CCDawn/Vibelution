"""Session branch head switching (T3-A2).

Moving the head is append-only: a ``branch_rebase`` marker with
``operation="head_select"`` records the new leaf, the shared fold recomputes
the active path for every reader, and the full session detail snapshot is
published so clients never derive the tree locally.
"""

from __future__ import annotations

from typing import Any

from core.chat.conversation_branches import resolve_head_leaf


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def switch_session_head(session_id: str, node_id: str) -> dict[str, Any]:
    """Point the session's active branch head at a version leaf."""

    s = _service()
    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    normalized_node_id = str(node_id or "").strip()
    if not normalized_node_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="请选择要切换的对话版本。", en="Choose a conversation version to switch to.")
        )
    admit_lock = s._session_submit_admit_lock(conversation_id)
    admit_lock.acquire()
    try:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(conversation_id, conversation=conversation)
        if s._is_session_running(conversation_id):
            raise s.SessionBusyError(
                s.text_for(
                    lang,
                    zh="当前回答仍在进行，请先停止后再切换版本。",
                    en="The current turn is still running; stop it before switching versions.",
                )
            )
        events = s._load_session_conversation_events_cached(conversation_id)
        if not events:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="当前会话还没有可切换的历史版本。",
                    en="This session has no conversation versions to switch between.",
                )
            )
        view = s.analyze_conversation_branches(events)
        leaf = resolve_head_leaf(view, normalized_node_id)
        if leaf is None:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="找不到要切换的对话版本，请刷新后重试。",
                    en="The requested conversation version was not found; refresh and try again.",
                )
            )
        if leaf.node_id != view.active_leaf_id:
            s._append_session_conversation_event(
                conversation_id,
                leaf.turn_id,
                s.EVENT_BRANCH_REBASE,
                status="recorded",
                payload={
                    "operation": "head_select",
                    "branchId": leaf.branch_id,
                    "fromEventId": leaf.event_id,
                    "replacedTurnIds": [],
                    "baseMessageId": normalized_node_id,
                },
                source="session_head_select",
                visible_in_model=False,
                projection_kind="session_branch_rebase",
                parent_event_id=leaf.event_id,
            )
    finally:
        admit_lock.release()
    s._publish_session_detail_snapshot(conversation_id)
    return s.get_session_detail(conversation_id) or {}
