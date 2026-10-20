"""Seal room-bound meeting speakers' child-session tasks at meeting close.

Room-bound discussions resolve one hidden Child Session per (room scope,
Agent) — the meeting transcript lives in the chat room, so those speaker
sessions never run a turn of their own. ``create_child_session`` registers a
``kind=child_session`` runtime task for each one, and with ``auto_start=False``
that task starts (and, without this module, ends) at status ``idle``: it sits
in the unified registry's active bucket forever and piles up in the topbar
task panel as one "空闲" row per speaker per round.

Closing the meeting is the authoritative "the speakers' job is done" moment.
Only never-started ``idle`` tasks are sealed: a queued or running speaker
still owns a live turn and keeps its own lifecycle. Sealing is idempotent and
fail-open — a housekeeping failure must never roll back a committed closure.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SEAL_REASON_MEETING_CLOSED = "meeting_closed_speaker_idle"

__all__ = [
    "SEAL_REASON_MEETING_CLOSED",
    "seal_closed_meeting_participant_tasks",
    "seal_room_participant_tasks",
]


def seal_closed_meeting_participant_tasks(
    meeting_round: Mapping[str, Any],
    *,
    store: Any = None,
) -> dict[str, Any]:
    """Seal the speaker tasks of the room a closed meeting was bound to."""

    room_id = str((meeting_round or {}).get("linkedChatRoomId") or "").strip()
    if not room_id:
        return {"roomId": "", "sealed": 0, "skipped": 0, "sealedTaskIds": []}
    return seal_room_participant_tasks(room_id, store=store)


def seal_room_participant_tasks(
    room_id: str,
    *,
    store: Any = None,
) -> dict[str, Any]:
    """Mark one room's participant child-session tasks terminal.

    Reads the room's persisted Agent-to-Child-Session bindings, then moves
    every still-``idle`` ``child_session`` registry task to ``completed``.
    Unknown sessions, non-child tasks and started tasks are skipped; the
    registry's own ``mark_task_terminal`` keeps the operation idempotent.
    """

    normalized_room_id = str(room_id or "").strip()
    report: dict[str, Any] = {
        "roomId": normalized_room_id,
        "sealed": 0,
        "skipped": 0,
        "sealedTaskIds": [],
    }
    if not normalized_room_id:
        return report
    try:
        session_ids = _room_participant_session_ids(normalized_room_id)
    except Exception as exc:  # noqa: BLE001 - housekeeping must not raise
        _record_seal_failure(
            room_id=normalized_room_id,
            stage="room_read",
            error=exc,
        )
        return report
    if not session_ids:
        return report
    try:
        selected_store = store if store is not None else _default_store()
        for session_id in session_ids:
            state = selected_store.load_state(session_id)
            if (
                not isinstance(state, Mapping)
                or str(state.get("kind") or "") != "child_session"
                or str(state.get("status") or "") != "idle"
            ):
                report["skipped"] = int(report["skipped"]) + 1
                continue
            selected_store.mark_task_terminal(
                session_id,
                status="completed",
                reason=SEAL_REASON_MEETING_CLOSED,
            )
            report["sealed"] = int(report["sealed"]) + 1
            report["sealedTaskIds"].append(session_id)
    except Exception as exc:  # noqa: BLE001 - housekeeping must not raise
        _record_seal_failure(
            room_id=normalized_room_id,
            stage="registry_seal",
            error=exc,
        )
    return report


def _room_participant_session_ids(room_id: str) -> list[str]:
    from core.web.services import chat_room_service

    detail = chat_room_service.get_chat_room_detail(room_id, reconcile=False)
    session_ids: list[str] = []
    for participant in list((detail or {}).get("participants") or []):
        if not isinstance(participant, Mapping):
            continue
        session_id = str(participant.get("sessionId") or "").strip()
        if session_id and session_id not in session_ids:
            session_ids.append(session_id)
    return session_ids


def _default_store() -> Any:
    from core.web.services import runtime_task_registry

    return runtime_task_registry.default_store()


def _record_seal_failure(*, room_id: str, stage: str, error: Exception) -> None:
    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_closure",
            "meeting_rounds.speaker_task_seal_failed",
            message="Meeting closed but its speaker child-session tasks could not be sealed.",
            level="warning",
            outcome="degraded",
            fields={
                "roomId": room_id,
                "stage": stage,
                "errorType": type(error).__name__,
            },
            lifecycle=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never alter closure
        return
