"""Optional compare-and-send guard for ordinary native continuation messages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from core.chat.conversation_branches import analyze_conversation_branches
from core.chat.turn_journal import TERMINAL_EVENTS, fold_active_events, latest_open_turn_id

from . import journal_bridge
from .admission_lock import session_has_active_work_run
from .queued_turns import session_queued_turn_rows
from .retry import _ensure_ordinary_owner


def normalize_continuation_expected(s, value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    limits = {"turnId": 160, "headId": 200, "agentId": 160}
    if (not isinstance(value, Mapping) or set(value) != {*limits, "ledgerSeq"}
            or any(not isinstance(value[key], str) or not value[key].strip()
                   or len(value[key]) > limit for key, limit in limits.items())
            or isinstance(value["ledgerSeq"], bool) or not isinstance(value["ledgerSeq"], int)
            or value["ledgerSeq"] < 1):
        raise s.SessionValidationError("继续需要完整、有效的会话快照。")
    return {**{key: value[key].strip() for key in limits}, "ledgerSeq": value["ledgerSeq"]}


def continuation_fingerprint_base(base: str, expected: dict[str, Any]) -> str:
    encoded = json.dumps({"base": base, "continuation": expected}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_continuation(s, session_id: str, expected: dict[str, Any]) -> None:
    """Caller holds session admission through the accepted user journal marker.

    This guard never reconciles or repairs. Only an exact, settled ordinary
    session snapshot can enter the unchanged native new-message acceptance.
    """
    def conflict() -> None:
        raise s.SessionBusyError("会话已推进或当前状态不能继续，请刷新后重试。")

    conversation = s.load_session_chat_state(s.PROJECT_ROOT, session_id)
    if conversation is None:
        raise s.SessionNotFoundError("Session not found")
    s._ensure_session_mutable(session_id, conversation=conversation)
    _ensure_ordinary_owner(s, conversation, expected)
    events = journal_bridge.load_session_conversation_events_snapshot(session_id, project_root=s.PROJECT_ROOT)
    if (not events or events[-1].sequence != expected["ledgerSeq"]
            or s._is_session_running(session_id) or latest_open_turn_id(events)
            or session_queued_turn_rows(conversation)
            or session_has_active_work_run(s, session_id, expected["turnId"])):
        conflict()
    view = analyze_conversation_branches(events)
    active = fold_active_events(events)
    terminals = [event for event in active if event.event_type in TERMINAL_EVENTS]
    users = [event for event in active if event.event_type == "user_message"
             and (event.payload.get("metadata") or {}).get("kind")
             not in {"user_guidance", "user_interrupt_guidance"}]
    if (view.active_leaf_id != expected["headId"] or not terminals or not users
            or terminals[-1].turn_id != expected["turnId"] or users[-1].turn_id != expected["turnId"]):
        conflict()
    terminal = terminals[-1]
    statuses = {str(terminal.status or "").strip().lower(),
                str(terminal.payload.get("finalStatus") or "").strip().lower()}
    if (terminal.event_type == "turn_interrupted"
            or statuses & {"stopped", "stopped_by_user", "needs_continue", "paused_limit"}):
        return
    error = conversation.get("last_turn_error") or conversation.get("lastTurnError") or {}
    if (isinstance(error, Mapping)
            and terminal.event_type == "turn_failed" and not statuses & {"completed", "success"}
            and str(error.get("turn_id") or error.get("turnId") or "").strip() == expected["turnId"]
            and str(error.get("reason_code") or error.get("reasonCode") or "").strip() == "iteration_limit_reached"):
        return
    conflict()
