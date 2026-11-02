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

Writer status (batch 5): the settlement-layer "ended on a question" fact is
the turn's own final visible text — ``persist.py``'s successful-turn
collection point calls :func:`stamp_turn_pending_question` with it, so a
completed turn whose reply ends asking its person freezes that question into
the slot (``session_waits_for_person`` then holds the floor for the person).
No PA direct-session ask_user-class tool exists yet
(``virtual_human_life``'s ``ask_user`` act lives in the plugin's own plan
store; chat_room ``nextAction=clarify`` is room-domain), so the text
heuristic on the settled reply IS the writer signal — ``set_...`` stays the
sanctioned direct entry point, the stamp is the settlement-side one.

Field style mirrors the frozen approval-pending shape
(``tool_approvals._ApprovalRequest``): explicit camelCase fields, a
monotonic lifecycle (askedAt -> consumedAt), and no mutable status enum —
an empty ``consumedAt`` IS the pending state.

Module-level imports stay dependency-free (facade is imported lazily inside
functions) so any session-side module can import this one safely.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

PENDING_QUESTION_STATE_KEY = "pendingQuestion"

_MAX_QUESTION_TEXT_CHARS = 4000

# Writer-side cap (persist.py settlement hook): the slot carries the frozen
# question for surfacing, not the whole reply — 200 chars keeps the tail (the
# actual question ending) without storing a paragraph.
_WRITER_MAX_QUESTION_TEXT_CHARS = 200

_QUESTION_ENDINGS = ("?", "？")


def _service():
    from core.web.services import session_service

    return session_service


def _new_pending_question_id() -> str:
    return f"pq-{uuid.uuid4().hex[:12]}"


def pending_question_id_for_turn(session_id: str, turn_id: str) -> str:
    """Deterministic slot id derived from the settling turn and session.

    A replayed settlement stamps the same id again, so the write stays
    idempotent; a turn without an id falls back to a random id rather than
    letting every turnless settlement share one identity.
    """

    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_turn_id:
        return _new_pending_question_id()
    digest = hashlib.sha1(
        f"{str(session_id or '').strip()}\x1f{normalized_turn_id}".encode()
    ).hexdigest()[:12]
    return f"pq-{digest}"


def trailing_question_text(visible_text: str) -> str:
    """The question an assistant reply ended on, or ``""`` when it did not ask.

    Reads the final visible assistant text (thinking/tool segments already
    removed upstream): the last non-empty paragraph must end — after trim —
    with ``?``/``？``. Anything else (statement, tool-only note) is not the
    assistant holding its floor for an answer, so no slot is written.
    """

    for paragraph in reversed(
        str(visible_text or "").replace("\r\n", "\n").split("\n\n")
    ):
        candidate = paragraph.strip()
        if not candidate:
            continue
        return candidate if candidate.endswith(_QUESTION_ENDINGS) else ""
    return ""


def _writer_slot(session_id: str, turn_id: str, question_text: str) -> dict[str, Any]:
    from core.web.services import session_service

    return {
        "id": pending_question_id_for_turn(session_id, turn_id),
        "questionText": question_text[-_WRITER_MAX_QUESTION_TEXT_CHARS:],
        "askedAt": session_service._now_timestamp(),
        "consumedAt": "",
    }


def stamp_turn_pending_question(
    conversation: dict[str, Any] | None,
    *,
    session_id: str,
    turn_id: str,
    visible_text: str,
) -> dict[str, Any] | None:
    """Writer entry: freeze a question-ending turn's question into its slot.

    Called from the single successful-turn collection point
    (``persist._persist_session_turn_result``) with the turn's final visible
    assistant text, mutating the in-flight conversation dict so the slot lands
    in the SAME atomic chat-state commit that stamps ``last_turn_status`` —
    no second write, no extra lock window. Single-slot semantics: a fresh
    question overwrites whatever occupied the slot; non-question endings and
    failed/aborted turns write nothing and leave an existing slot untouched
    (clearing stays the person-message consume side's job). Never raises —
    persistence must not break turn finalization. Returns the slot written,
    or None when nothing was written.
    """

    try:
        if not isinstance(conversation, dict):
            return None
        question_text = trailing_question_text(visible_text)
        if not question_text:
            return None
        slot = _writer_slot(session_id, turn_id, question_text)
        conversation[PENDING_QUESTION_STATE_KEY] = slot
        return dict(slot)
    except Exception:  # noqa: BLE001 - the slot write must never break settlement
        return None


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
    "pending_question_id_for_turn",
    "session_pending_question",
    "set_session_pending_question",
    "stamp_turn_pending_question",
    "trailing_question_text",
]
