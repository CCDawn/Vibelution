"""Whole-turn file rewind: preview and apply over the file-change ledger.

The ledger (``core/chat/file_change_ledger.py``) owns checkpoints; this
module is the session-facing service layer: session existence checks, error
translation, and audit scene events. Routes stay thin; the ledger stays the
only disk authority for checkpoint data.
"""

from __future__ import annotations

from typing import Any

from core.chat.file_change_ledger import (
    FileChangeRewindConflictError,
    apply_turn_rewind,
    preview_turn_rewind,
)


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def preview_session_rewind(session_id: str, turn_id: str) -> dict[str, Any] | None:
    """Preview the per-file rewind plan for one turn.

    Returns ``None`` when the session or the turn has no checkpoint at all;
    the route maps that to 404.
    """

    s = _service()
    lang = s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    if not normalized_turn_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="缺少要回退的轮次标识。", en="Missing the turn to rewind.")
        )
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    return preview_turn_rewind(
        s.PROJECT_ROOT,
        normalized_session_id,
        normalized_turn_id,
    )


def apply_session_rewind(
    session_id: str,
    turn_id: str,
    *,
    force: bool = False,
    requested_by: str = "operator",
) -> dict[str, Any]:
    """Restore every checkpointed file of one turn to its pre-image.

    Strict by default (any unsafe file rejects the whole batch); ``force``
    applies safe files per-file and reports the skipped ones. Repeated calls
    replay the stored audit result instead of touching files again.
    """

    s = _service()
    lang = s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    if not normalized_turn_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="缺少要回退的轮次标识。", en="Missing the turn to rewind.")
        )
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    try:
        result = apply_turn_rewind(
            s.PROJECT_ROOT,
            normalized_session_id,
            normalized_turn_id,
            force=bool(force),
            requested_by=str(requested_by or "").strip(),
        )
    except FileChangeRewindConflictError as exc:
        raise s.SessionRewindConflictError(
            s.text_for(
                lang,
                zh=str(exc),
                en="Some files changed after this turn wrote them; the batch rewind was rejected. Use force to restore only the safe files.",
            ),
            unsafe_files=list(exc.unsafe_files),
        ) from exc
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_rewind",
            "conversation.session.rewound",
            level="info",
            outcome="succeeded",
            message="Turn file changes rewound to pre-images.",
            fields={
                "sessionId": normalized_session_id,
                "turnId": normalized_turn_id,
                "mode": "force" if force else "strict",
                "appliedCount": len(result.get("applied") or []),
                "skippedCount": len(result.get("skipped") or []),
                "alreadyApplied": bool(result.get("alreadyApplied")),
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return result


__all__ = ["apply_session_rewind", "preview_session_rewind"]
