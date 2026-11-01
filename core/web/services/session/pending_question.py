"""Session pendingQuestion slot: one frozen question awaiting its person.

Claim scope: the single-slot ``pendingQuestion`` chat-state object (set /
consume / clear / read) plus the pending-shape read the waitsForPerson
predicate consumes. No projection, no UI surface, no writer wiring yet.

Batch-4 human-slot lane: an unconsumed slot means the assistant ended (or
paused) by asking its person something — the session is holding its floor
for that person even when the resting phase alone would not say so
(``managed_continuation.session_waits_for_person`` ORs the slot into its
verdict). One-time consumption: the next person message consumes the slot
(``consumedAt`` stamp); ``submit.py`` wires that on accepted raw
submissions and ``queued_turns.enqueue_session_queued_turn`` wires it on
accepted queued user rows.

Writer status (batch 4): no PA direct-session ask_user-class tool or
settlement-layer "ended on a question" signal exists today
(``virtual_human_life``'s ``ask_user`` act lives in the plugin's own plan
store; chat_room ``nextAction=clarify`` is room-domain; text heuristics are
explicitly out of scope). Phase 1 therefore ships storage + predicate +
consume + clear only. TODO(batch-5+): wire a writer once the assistant
settlement layer exposes a structured "asked the user X" fact — the setter
below is the only sanctioned entry point.

Field style mirrors the frozen approval-pending shape
(``tool_approvals._ApprovalRequest``): explicit camelCase fields, a
monotonic lifecycle (askedAt -> consumedAt), and no mutable status enum —
an empty ``consumedAt`` IS the pending state.

Module-level imports stay dependency-free (facade is imported lazily inside
functions) so any session-side module can import this one safely.
"""

from __future__ import annotations

import uuid
from typing import Any

PENDING_QUESTION_STATE_KEY = "pendingQuestion"

_MAX_QUESTION_TEXT_CHARS = 4000


def _service():
    from core.web.services import session_service

    return session_service


def _new_pending_question_id() -> str:
    return f"pq-{uuid.uuid4().hex[:12]}"


def _slot_is_pending(slot: Any) -> bool:
    return isinstance(slot, dict) and not str(slot.get("consumedAt") or "").strip()


def conversation_pending_question(conversation: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pending-shape read for predicates: the slot only when still unconsumed."""

    if not isinstance(conversation, dict):
        return None
    slot = conversation.get(PENDING_QUESTION_STATE_KEY)
    if not _slot_is_pending(slot):
        return None
    return dict(slot)


def session_pending_question(session_id: str) -> dict[str, Any] | None:
    """Read the session's slot as stored (pending or consumed); None when absent."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if not isinstance(conversation, dict):
        return None
    slot = conversation.get(PENDING_QUESTION_STATE_KEY)
    return dict(slot) if isinstance(slot, dict) and slot else None


def set_session_pending_question(
    session_id: str,
    *,
    question_text: str,
    question_id: str = "",
) -> dict[str, Any]:
    """Write the single slot, replacing whatever occupied it.

    Single-slot semantics: a fresh question supersedes a previous one (the
    person answers the latest ask, not a queue of them). Returns the stored
    slot; missing sessions raise ``SessionNotFoundError``.
    """

    s = _service()
    lang = s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    text = str(question_text or "").strip()
    if not text:
        raise s.SessionValidationError(
            s.text_for(lang, zh="待回答问题不能为空。", en="A pending question needs text.")
        )
    slot = {
        "id": str(question_id or "").strip() or _new_pending_question_id(),
        "questionText": text[:_MAX_QUESTION_TEXT_CHARS],
        "askedAt": s._now_timestamp(),
        "consumedAt": "",
    }
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        conversation[PENDING_QUESTION_STATE_KEY] = slot
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
    return dict(slot)


def consume_session_pending_question(
    session_id: str,
    *,
    consumed_by: str = "human_message",
) -> dict[str, Any] | None:
    """One-time consumption: stamp ``consumedAt`` on a pending slot.

    Idempotent — an absent slot or an already-consumed slot returns None (or
    the consumed slot) without touching state, so parallel submissions and
    replayed hooks cannot double-consume. Returns the consumed slot when a
    pending slot was stamped just now.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return None
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if not isinstance(conversation, dict):
            return None
        slot = conversation.get(PENDING_QUESTION_STATE_KEY)
        if not _slot_is_pending(slot):
            return None
        consumed = dict(slot)
        consumed["consumedAt"] = s._now_timestamp()
        consumed["consumedBy"] = str(consumed_by or "").strip() or "human_message"
        conversation[PENDING_QUESTION_STATE_KEY] = consumed
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
        return consumed


def clear_session_pending_question(session_id: str) -> bool:
    """Explicit clear action: drop the slot entirely (pending or consumed).

    Returns True when a slot was removed. This is the sanctioned reset for
    operators and future writers; normal lifecycle relies on consumption.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if not isinstance(conversation, dict):
            return False
        if PENDING_QUESTION_STATE_KEY not in conversation:
            return False
        conversation.pop(PENDING_QUESTION_STATE_KEY, None)
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
        return True


__all__ = [
    "PENDING_QUESTION_STATE_KEY",
    "clear_session_pending_question",
    "consume_session_pending_question",
    "conversation_pending_question",
    "session_pending_question",
    "set_session_pending_question",
]
