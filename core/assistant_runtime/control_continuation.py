"""Assistant-only compare-and-send over the unchanged native Session owner."""

from __future__ import annotations

import re
from typing import Any

CONTROL_CONTINUATION_MESSAGE = (
    "控制已交回，请先重新观察当前页面或授权窗口，再继续当前任务；不要重放未经确认的操作。"
)
_METADATA_KEY = "assistantControlContinuation"
_LIMITS = {"agentId": 160, "sessionId": 160, "turnId": 160, "headId": 200}


def normalize_control_continuation(value: object) -> dict[str, Any]:
    """Reject incomplete or coercible snapshots at every transport boundary."""
    if (type(value) is not dict or set(value) != {*_LIMITS, "ledgerSeq"}
            or any(type(value[key]) is not str or not value[key].strip()
                   or value[key] != value[key].strip() or len(value[key]) > limit
                   for key, limit in _LIMITS.items())
            or type(value["ledgerSeq"]) is not int or not 1 <= value["ledgerSeq"] <= 2**53 - 1):
        raise ValueError("Invalid control continuation snapshot")
    return dict(value)


def _conflict(s) -> None:
    raise s.SessionBusyError("控制交回后会话已推进或仍在等待，请刷新后重试。")


def _accepted_request(s, events, request_id: str, expected: dict[str, Any]) -> bool:
    """Only a fingerprinted native user acceptance can bypass the old CAS.

    A queued row, partial turn_started marker, legacy same-text message or
    control-store-only receipt is not acceptance. The unchanged submit owner
    validates the complete request fingerprint when it replays this receipt.
    """
    related = [event for event in events if event.correlation_id == request_id]
    users = [event for event in related if event.event_type == "user_message"]
    if not users:
        if related:
            _conflict(s)
        return False
    if len(users) != 1:
        _conflict(s)
    event = users[0]
    payload = event.payload
    metadata = payload.get("metadata") or {}
    if (not event.turn_id or not isinstance(metadata, dict)
            or metadata.get(_METADATA_KEY) != expected
            or payload.get("content") != CONTROL_CONTINUATION_MESSAGE
            or payload.get("source", "raw") != "raw"
            or payload.get("attachments") or payload.get("references")
            or not isinstance(metadata.get("clientSubmissionFingerprint"), str)
            or re.fullmatch(r"[a-f0-9]{64}", metadata["clientSubmissionFingerprint"]) is None):
        _conflict(s)
    return True


def _validate_idle_snapshot(s, session_id: str, conversation, events, expected) -> None:
    from core.chat.conversation_branches import analyze_conversation_branches
    from core.chat.session_activity import activity_outcome
    from core.chat.turn_journal import (
        TERMINAL_EVENTS,
        fold_active_events,
        latest_open_turn_id,
    )
    from core.web.services.session import tool_approvals
    from core.web.services.session.admission_lock import session_has_active_work_run
    from core.web.services.session.pending_question import conversation_pending_question
    from core.web.services.session.queued_turns import (
        QUEUED_TURN_HOLD_KEY,
        QUEUED_TURN_STATE_KEY,
    )

    raw_queue = conversation.get(QUEUED_TURN_STATE_KEY, [])
    with s._RUNNING_SESSIONS_LOCK:
        active_turn = bool(s._SESSION_ACTIVE_TURN_IDS.get(session_id))
    if (not events or events[-1].sequence != expected["ledgerSeq"]
            or s._is_session_running(session_id) or active_turn or latest_open_turn_id(events)
            or not isinstance(raw_queue, list) or raw_queue
            or conversation.get(QUEUED_TURN_HOLD_KEY)
            or conversation_pending_question(conversation) is not None
            or session_has_active_work_run(s, session_id, expected["turnId"])):
        _conflict(s)
    approvals = tool_approvals.list_tool_approval_requests(session_id)
    settled = {"accepted", "accepted_for_session", "accepted_for_session_tool", "accepted_with_action_window",
               "accepted_always", "declined", "cancelled", "expired"}
    if (not isinstance(approvals, list)
            or any(not isinstance(row, dict) or row.get("status") not in settled for row in approvals)):
        _conflict(s)
    active = fold_active_events(events)
    users = [event for event in active if event.event_type == "user_message"
             and (event.payload.get("metadata") or {}).get("kind")
             not in {"user_guidance", "user_interrupt_guidance"}]
    terminals = [event for event in active if event.event_type in TERMINAL_EVENTS]
    if (analyze_conversation_branches(events).active_leaf_id != expected["headId"]
            or not users or users[-1].turn_id != expected["turnId"]
            or not terminals or terminals[-1].turn_id != expected["turnId"]
            or terminals[-1].event_type != "turn_completed"):
        _conflict(s)
    terminal = terminals[-1]
    statuses = [value for value in (terminal.status, terminal.payload.get("finalStatus")) if value]
    if not statuses or any(activity_outcome(value) != "completed" for value in statuses):
        _conflict(s)


def submit_control_continuation(s, session_id: str, message: str, request_id: str,
                                expected: dict[str, Any]) -> dict[str, Any]:
    """Caller binds identity; the shared admission lock fences CAS through accept."""
    from core.web.services.session import journal_bridge
    from core.web.services.session.admission_lock import SessionAdmissionLock
    from core.web.services.session.retry import _ensure_ordinary_owner

    with SessionAdmissionLock(s.PROJECT_ROOT, session_id):
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
        if not isinstance(conversation, dict):
            raise s.SessionNotFoundError("Session not found")
        s._ensure_session_mutable(session_id, conversation=conversation)
        _ensure_ordinary_owner(s, conversation, expected)
        events = journal_bridge.load_session_conversation_events_snapshot(session_id, project_root=s.PROJECT_ROOT)
        if not _accepted_request(s, events, request_id, expected):
            _validate_idle_snapshot(s, session_id, conversation, events, expected)
            # The optional development control store may have reserved an id
            # before a crash. Its row cannot prove native user acceptance.
            from core.web.services.session.admission import (
                get_development_submission_admission_runtime,
            )
            runtime = get_development_submission_admission_runtime(s.PROJECT_ROOT)
            if runtime is not None and runtime.existing(session_id=session_id, client_submission_id=request_id) is not None:
                _conflict(s)
        # Metadata participates in the native submission fingerprint. Replays
        # therefore bind the exact original snapshot as well as text/requestId.
        return s.submit_session_message(
            session_id, message, client_submission_id=request_id, queue_if_busy=False,
            message_metadata={_METADATA_KEY: dict(expected)},
            include_started_turn_id=True, lightweight_response=True,
        )
