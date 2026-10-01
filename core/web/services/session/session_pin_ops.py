"""Session pin/unpin ops for the session list.

Deliberately a standalone module: pin state lives only on the SQLite
directory row (``pinned_at_ms``), so this op needs neither the chat-state
lock nor the session_ops update pipeline. The chat-state conversation
document and the turn journal stay untouched.
"""

from __future__ import annotations


def _service():
    from core.web.services import session_service

    return session_service


def set_chat_session_pinned(session_id: str, *, pinned: bool) -> dict:
    """Pin or unpin one session for pinned-first list ordering."""

    s = _service()

    lang = s.get_web_language()
    conversation_id = str(session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    from . import directory_bridge
    from . import directory_runtime

    store = directory_runtime.get_open_directory_store()
    if store is None:
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="会话目录不可用，暂无法置顶。",
                en="Session directory is unavailable; pinning is disabled.",
            )
        )
    result = store.repository.set_session_pinned(
        conversation_id,
        pinned=bool(pinned),
    ).result(timeout=directory_bridge._SYNC_TIMEOUT_SECONDS)
    if result is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    s._invalidate_session_list_cache()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_lifecycle",
            "conversation.session.pin.updated",
            level="info",
            outcome="pinned" if pinned else "unpinned",
            message="Session pin state updated.",
            fields={
                "sessionId": conversation_id,
                "pinned": bool(pinned),
                "pinnedAtMs": result.get("pinnedAtMs"),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"session pin scene log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )
    return {
        "id": conversation_id,
        "pinned": bool(pinned),
        "pinnedAtMs": result.get("pinnedAtMs"),
    }
