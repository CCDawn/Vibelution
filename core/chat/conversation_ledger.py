# -*- coding: utf-8 -*-
"""Single-source conversation ledger.

The ledger is the authoritative append-only event stream for a chat session.
UI snapshots, model context, recovery state, and stream ordering must be
derived from this stream instead of maintaining independent facts.

This module intentionally wraps the existing turn journal storage path during
the migration. Callers should depend on this ledger API; the physical file can
move later without changing conversation-flow code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .turn_journal import (
    AUDIT_ONLY_EVENT_TYPES,
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_CLI_TASK_SENT,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    MODEL_VISIBLE_EVENT_TYPES,
    TURN_INTERRUPTED_MARKER,
    TurnJournalEvent,
    VOLATILE_MODEL_EVENT_TYPES,
    append_interrupted_if_open,
    append_turn_event,
    event_has_model_projection,
    event_projection_category,
    latest_open_turn_id,
    load_turn_events,
    model_messages_from_events,
    model_visible_messages_from_events,
    turn_journal_path,
)


ConversationLedgerEvent = TurnJournalEvent


@dataclass(frozen=True)
class ConversationLedgerProjection:
    """A deterministic projection derived from ledger events."""

    events: list[ConversationLedgerEvent]
    model_messages: list[dict[str, Any]] = field(default_factory=list)
    visible_messages: list[dict[str, Any]] = field(default_factory=list)
    latest_seq: int = 0
    latest_event_id: str = ""
    open_turn_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "ledgerSeq": self.latest_seq,
            "ledgerEventId": self.latest_event_id,
            "openTurnId": self.open_turn_id,
            "eventCount": len(self.events),
        }


def conversation_ledger_path(project_root: Path, session_id: str) -> Path:
    return turn_journal_path(project_root, session_id)


def append_conversation_event(
    project_root: Path,
    session_id: str,
    turn_id: str,
    event_type: str,
    *,
    status: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "",
    timestamp: str = "",
    parent_event_id: str = "",
    visible_in_model: bool = True,
    projection_kind: str = "",
    provider_role: str = "",
    tool_call_id: str = "",
    correlation_id: str = "",
    source_kind: str = "",
) -> ConversationLedgerEvent:
    return append_turn_event(
        project_root,
        session_id,
        turn_id,
        event_type,
        status=status,
        payload=payload,
        source=source,
        timestamp=timestamp,
        parent_event_id=parent_event_id,
        visible_in_model=visible_in_model,
        projection_kind=projection_kind,
        provider_role=provider_role,
        tool_call_id=tool_call_id,
        correlation_id=correlation_id,
        source_kind=source_kind,
    )


def load_conversation_events(project_root: Path, session_id: str) -> list[ConversationLedgerEvent]:
    return load_turn_events(project_root, session_id)


def conversation_model_messages_from_events(
    events: Iterable[ConversationLedgerEvent],
) -> list[dict[str, Any]]:
    return model_messages_from_events(events)


def conversation_visible_messages_from_events(
    events: Iterable[ConversationLedgerEvent],
) -> list[dict[str, Any]]:
    return model_visible_messages_from_events(events)


def project_conversation_ledger(
    events: Iterable[ConversationLedgerEvent],
    *,
    include_model_messages: bool = True,
    include_visible_messages: bool = False,
) -> ConversationLedgerProjection:
    event_list = list(events or [])
    latest = event_list[-1] if event_list else None
    return ConversationLedgerProjection(
        events=event_list,
        model_messages=conversation_model_messages_from_events(event_list) if include_model_messages else [],
        visible_messages=conversation_visible_messages_from_events(event_list) if include_visible_messages else [],
        latest_seq=int(getattr(latest, "sequence", 0) or 0) if latest is not None else 0,
        latest_event_id=str(getattr(latest, "event_id", "") or "") if latest is not None else "",
        open_turn_id=latest_open_turn_id(event_list),
    )


def latest_ledger_sequence(project_root: Path, session_id: str) -> int:
    events = load_conversation_events(project_root, session_id)
    return int(events[-1].sequence or 0) if events else 0


def reconcile_open_conversation_turn(
    project_root: Path,
    session_id: str,
    *,
    active_turn_id: str = "",
    reason: str = "process_restarted",
    source: str = "conversation_ledger_reconcile",
) -> ConversationLedgerEvent | None:
    return append_interrupted_if_open(
        project_root,
        session_id,
        active_turn_id=active_turn_id,
        reason=reason,
        source=source,
    )


__all__ = [
    "ConversationLedgerEvent",
    "ConversationLedgerProjection",
    "AUDIT_ONLY_EVENT_TYPES",
    "EVENT_ASSISTANT_DELTA_COMMITTED",
    "EVENT_ASSISTANT_MESSAGE",
    "EVENT_ASSISTANT_PARTIAL",
    "EVENT_CLI_SESSION_LIFECYCLE",
    "EVENT_CLI_TASK_RESULT",
    "EVENT_CLI_TASK_SENT",
    "EVENT_COMPACTION_CHECKPOINT",
    "EVENT_TOOL_CALL_STARTED",
    "EVENT_TOOL_RESULT",
    "EVENT_TURN_COMPLETED",
    "EVENT_TURN_CONTEXT",
    "EVENT_TURN_FAILED",
    "EVENT_TURN_INTERRUPTED",
    "EVENT_TURN_STARTED",
    "EVENT_USER_MESSAGE",
    "MODEL_VISIBLE_EVENT_TYPES",
    "TURN_INTERRUPTED_MARKER",
    "VOLATILE_MODEL_EVENT_TYPES",
    "append_conversation_event",
    "conversation_ledger_path",
    "conversation_model_messages_from_events",
    "conversation_visible_messages_from_events",
    "event_has_model_projection",
    "event_projection_category",
    "latest_ledger_sequence",
    "load_conversation_events",
    "project_conversation_ledger",
    "reconcile_open_conversation_turn",
]
