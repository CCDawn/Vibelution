"""Third wake signal for sessions resting on ``needs_continue``/``paused_limit``.

A session whose turn settled into ``needs_continue``/``paused_limit`` has
finished its work-run: the only regeneration entry today is a human sending
"继续" (``continuation_expected`` snapshot CAS in ``submit``). Machine sources
that legitimately own the task (agent inbox tasks, source-collection stages,
task notifications) had no way to nudge the session forward. This module adds
one audited, capped admission channel:

``request_managed_continuation(session_id, *, source, reason)`` submits a
single continuation turn under the dedicated ``managed_continuation`` message
source. The worker's internal auto-continue gate
(``_session_context_allows_internal_auto_continue``) gains a double-confirm
branch for that source, mirroring the ``external_agent_task`` shape.

Hard rails:
- waitsForPerson: when the session rests on a turn whose last user input was
  written by a person (``native.py`` operator-event predicate shape), every
  machine request is refused (``rejected_waiting_for_person``). Human
  messages keep their existing "继续" channel untouched.
- Cap: per resting chain, at most ``MANAGED_CONTINUATION_LIMIT`` managed
  continuations (aligned with the external-agent task cap of 3). The count is
  persisted in the session chat state, so a restart cannot reset it. Beyond
  the cap the refusal is visible (lifecycle event), not silent.
- Fingerprint safety: the channel never carries a ``continuation_expected``
  snapshot, so it cannot perturb the human "继续" fingerprint/CAS contract.

Module-level imports stay dependency-free (facade is imported lazily inside
functions) so any session-side module can import this one safely.
"""

from __future__ import annotations

from typing import Any

# Dedicated message source; also the payload["source"] recorded on the
# journal user_message event, which is what chain detection reads back.
MANAGED_CONTINUATION_MESSAGE_SOURCE = "managed_continuation"

# Aligned with external_agent/service.py::_RESUMABLE_PHASES semantics.
MANAGED_CONTINUATION_RESUMABLE_PHASES = frozenset({"needs_continue", "paused_limit"})

# Aligned with external_agent/service.py::_MAX_MANAGED_CONTINUATIONS.
MANAGED_CONTINUATION_LIMIT = 3

MANAGED_CONTINUATION_STATE_KEY = "managedContinuation"

MANAGED_CONTINUATION_PROMPT = (
    "继续推进当前会话中的剩余工作；复用已有上下文，完成剩余步骤并给出最终结论。"
)

_MAX_SOURCE_CHARS = 120
_MAX_REASON_CHARS = 500
_MAX_PROMPT_CHARS = 8000

EVENT_USER_MESSAGE = "user_message"


def _service():
    from core.web.services import session_service

    return session_service

# Operator-event predicate shape (core/assistant_runtime/native.py
# operator_event): anything that does not clearly read as a person message is
# treated as machine. Deliberately weaker than native on identity proof only
# (clientSubmissionId/correlation): this gate asks "person or machine", not
# "provably the named operator".


def _journal_user_event_is_person_message(event: Any) -> bool:
    payload = getattr(event, "payload", None)
    payload = payload if isinstance(payload, dict) else {}
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    if str(getattr(event, "source", "") or "").strip() != "submit_session_message":
        return False
    if str(getattr(event, "source_kind", "") or "").strip() not in {"", "user", "operator"}:
        return False
    if str(payload.get("source") or "").strip() != "raw":
        return False
    if metadata.get("kind") not in (None, "", "user"):
        return False
    if metadata.get("source") not in (None, "", "user", "operator", "raw"):
        return False
    if any(
        metadata.get(key) not in (None, "", "user", "operator")
        for key in ("actor", "actorId", "actorType", "sourceKind")
    ):
        return False
    if any(metadata.get(key) for key in ("agentId", "actorAgentId", "proactive", "system", "sourceAgentId")):
        return False
    if not bool(getattr(event, "visible_in_model", True)):
        return False
    return True


def _last_user_journal_event(s: Any, session_id: str) -> Any:
    from . import journal_bridge

    events = journal_bridge.load_session_conversation_events_cached(
        session_id, project_root=s.PROJECT_ROOT
    )
    last_user = None
    for event in events:
        if str(getattr(event, "event_type", "") or "").strip() == EVENT_USER_MESSAGE:
            last_user = event
    return last_user


def session_resting_phase(conversation: dict[str, Any] | None) -> str:
    """Return the session's resting phase when it rests on an unfinished turn."""

    status = str((conversation or {}).get("last_turn_status") or "").strip().lower()
    return status if status in MANAGED_CONTINUATION_RESUMABLE_PHASES else ""


def session_waits_for_person(
    s: Any,
    session_id: str,
    *,
    conversation: dict[str, Any] | None = None,
) -> bool:
    """True when the session rests on a turn whose last user input was human.

    Shared gate predicate for the three machine wake surfaces: the managed
    continuation channel, the queued-notice drain, and proactive plugin
    turns. Sessions not resting in needs_continue/paused_limit never count as
    waiting (ready/idle sessions keep their normal machine wake behavior).
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    if not isinstance(conversation, dict):
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if not isinstance(conversation, dict):
        return False
    if not session_resting_phase(conversation):
        return False
    last_user = _last_user_journal_event(s, normalized_session_id)
    if last_user is None:
        return False
    return _journal_user_event_is_person_message(last_user)


def runtime_notice_head_blocked_waiting_for_person(
    s: Any,
    session_id: str,
    *,
    conversation: dict[str, Any] | None = None,
) -> bool:
    """Drain gate: a machine-notice run must not pull up a person-waiting session.

    Only pure machine-notice heads (task_notification/subagent_message) are
    gated: user rows carry explicit user intent, and control notices settle
    journal-only without starting a model turn, so neither may be held back.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    if not isinstance(conversation, dict):
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if not isinstance(conversation, dict) or s._is_session_running(normalized_session_id):
        return False
    from .queued_turns import RUNTIME_NOTICE_KINDS, session_queued_turn_rows

    head = next(
        (
            row
            for row in session_queued_turn_rows(conversation)
            if str(row.get("status") or "").strip() == "queued"
        ),
        None,
    )
    if head is None:
        return False
    if str(head.get("kind") or "").strip() not in RUNTIME_NOTICE_KINDS:
        return False
    return session_waits_for_person(s, normalized_session_id, conversation=conversation)


def _managed_continuation_chain_count(
    s: Any,
    session_id: str,
    conversation: dict[str, Any],
) -> int:
    """Managed continuations already spent inside the current resting chain.

    The chain stays alive only while the last user message on the journal is
    itself a managed continuation; any other settlement (human "继续", inbox
    wake, queued user turn) starts a fresh chain with count 0. The count is
    read from the persisted session state, so restarts cannot reset it.
    """

    last_user = _last_user_journal_event(s, session_id)
    if last_user is None:
        return 0
    payload = getattr(last_user, "payload", None)
    payload = payload if isinstance(payload, dict) else {}
    if str(payload.get("source") or "").strip() != MANAGED_CONTINUATION_MESSAGE_SOURCE:
        return 0
    state = conversation.get(MANAGED_CONTINUATION_STATE_KEY)
    state = state if isinstance(state, dict) else {}
    try:
        return max(0, int(state.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def _write_managed_continuation_state(
    s: Any,
    session_id: str,
    *,
    count: int,
    source: str,
    reason: str,
) -> None:
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if conversation is None:
            return
        conversation[MANAGED_CONTINUATION_STATE_KEY] = {
            "count": int(count),
            "lastSource": str(source or "").strip(),
            "lastReason": str(reason or "").strip(),
            "updatedAt": s._now_timestamp(),
        }
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)


def _restore_managed_continuation_state(
    s: Any,
    session_id: str,
    previous: dict[str, Any] | None,
) -> None:
    try:
        with s._CHAT_STATE_LOCK:
            conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
            if conversation is None:
                return
            if previous is None:
                conversation.pop(MANAGED_CONTINUATION_STATE_KEY, None)
            else:
                conversation[MANAGED_CONTINUATION_STATE_KEY] = dict(previous)
            conversation["updated_at"] = s._now_timestamp()
            s.save_session_chat_state(s.PROJECT_ROOT, session_id, conversation)
    except Exception:  # noqa: BLE001 - rollback must never mask the submit failure
        pass


def request_managed_continuation(
    session_id: str,
    *,
    source: str,
    reason: str,
    prompt: str = "",
) -> dict[str, Any]:
    """Admit one machine-sourced continuation turn for a resting session.

    Returns a structured receipt; only a missing session raises. Refusal
    reasons are explicit so callers can surface them instead of retry-blind.
    """

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError("Session not found")
    normalized_source = str(source or "").strip()
    if not normalized_source:
        raise s.SessionValidationError("managed continuation requires a non-empty source.")
    if len(normalized_source) > _MAX_SOURCE_CHARS:
        raise s.SessionValidationError("managed continuation source is too long.")
    normalized_reason = str(reason or "").strip()[:_MAX_REASON_CHARS]
    normalized_prompt = str(prompt or "").strip()[:_MAX_PROMPT_CHARS] or MANAGED_CONTINUATION_PROMPT

    def rejected(reason_code: str, **fields: Any) -> dict[str, Any]:
        return {
            "accepted": False,
            "reason": reason_code,
            "sessionId": normalized_session_id,
            "source": normalized_source,
            **fields,
        }

    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        raise s.SessionNotFoundError("Session not found")

    from .queued_turns import (
        MACHINE_NOTICE_KINDS,
        session_queue_hold_active,
        session_queued_turn_rows,
    )

    if s._is_session_running(normalized_session_id):
        return rejected("rejected_session_busy")
    from core.web.services.external_agent.approval_binding import is_external_session

    if is_external_session(conversation):
        # External task sessions have their own managed continuation lane
        # (external_agent/service.py); a second one would race its revision
        # fence and its queue lockout.
        return rejected("rejected_external_session")
    if session_queue_hold_active(normalized_session_id):
        return rejected("rejected_queue_hold")

    resting_phase = session_resting_phase(conversation)
    if not resting_phase:
        return rejected(
            "rejected_not_resumable",
            lastTurnStatus=str(conversation.get("last_turn_status") or "").strip(),
        )
    if any(
        str(row.get("status") or "").strip() == "queued"
        and str(row.get("kind") or "").strip() not in MACHINE_NOTICE_KINDS
        for row in session_queued_turn_rows(conversation)
    ):
        # Pending user rows own the next turn; a managed continuation must
        # not jump the user's queue.
        return rejected("rejected_queued_user_turns")
    if session_waits_for_person(s, normalized_session_id, conversation=conversation):
        return rejected(
            "rejected_waiting_for_person",
            restingPhase=resting_phase,
        )

    chain_count = _managed_continuation_chain_count(s, normalized_session_id, conversation)
    if chain_count >= MANAGED_CONTINUATION_LIMIT:
        # Visible failure state: the refusal lands in the session lifecycle
        # stream instead of vanishing into a returned dict.
        s._record_session_turn_lifecycle_event(
            normalized_session_id,
            "managed_continuation_limit_reached",
            level="warning",
            outcome="failed",
            fields={
                "managedContinuationCount": chain_count,
                "managedContinuationLimit": MANAGED_CONTINUATION_LIMIT,
                "source": normalized_source,
                "reason": normalized_reason,
                "restingPhase": resting_phase,
            },
        )
        return rejected(
            "rejected_continuation_limit",
            restingPhase=resting_phase,
            managedContinuationCount=chain_count,
            managedContinuationLimit=MANAGED_CONTINUATION_LIMIT,
        )

    next_count = chain_count + 1
    previous_state = conversation.get(MANAGED_CONTINUATION_STATE_KEY)
    previous_state = dict(previous_state) if isinstance(previous_state, dict) else None
    # Persist the attempt before submitting so a restart can never lose spent
    # attempts (the counter is the cap's source of truth, not process memory).
    _write_managed_continuation_state(
        s,
        normalized_session_id,
        count=next_count,
        source=normalized_source,
        reason=normalized_reason,
    )
    try:
        submitted = s.submit_session_message(
            normalized_session_id,
            normalized_prompt,
            message_source=MANAGED_CONTINUATION_MESSAGE_SOURCE,
            message_metadata={
                "kind": MANAGED_CONTINUATION_MESSAGE_SOURCE,
                "source": normalized_source,
                "reason": normalized_reason,
                "managedContinuationCount": next_count,
            },
            write_intent=False,
            include_started_turn_id=True,
            lightweight_response=True,
        )
    except Exception:
        _restore_managed_continuation_state(s, normalized_session_id, previous_state)
        raise
    turn_id = str(submitted.get("startedTurnId") or "").strip()
    s._record_session_turn_lifecycle_event(
        normalized_session_id,
        "managed_continuation_admitted",
        turn_id=turn_id,
        outcome="accepted",
        fields={
            "managedContinuationCount": next_count,
            "managedContinuationLimit": MANAGED_CONTINUATION_LIMIT,
            "source": normalized_source,
            "reason": normalized_reason,
            "restingPhase": resting_phase,
        },
    )
    return {
        "accepted": True,
        "sessionId": normalized_session_id,
        "turnId": turn_id,
        "restingPhase": resting_phase,
        "managedContinuationCount": next_count,
        "managedContinuationLimit": MANAGED_CONTINUATION_LIMIT,
        "source": normalized_source,
        "reason": normalized_reason,
    }


__all__ = [
    "MANAGED_CONTINUATION_LIMIT",
    "MANAGED_CONTINUATION_MESSAGE_SOURCE",
    "MANAGED_CONTINUATION_PROMPT",
    "MANAGED_CONTINUATION_RESUMABLE_PHASES",
    "MANAGED_CONTINUATION_STATE_KEY",
    "request_managed_continuation",
    "runtime_notice_head_blocked_waiting_for_person",
    "session_resting_phase",
    "session_waits_for_person",
]
