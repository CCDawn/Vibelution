"""Session admission events for input that arrives during a running turn.

One fact family covers both deliveries:

- ``guide`` injects the text into the running turn (the existing steer
  user message remains the only model-visible copy).
- ``queue`` waits for the next turn. The queue row stays the operational
  store for edit, reorder, and pause.

A guide whose user-message write loses the terminal race is not dropped.
The same ``steerId`` is retargeted to ``queue`` and enqueued. Promotion
into the next user message is a sibling event written beside that message.
These events are never model-visible and are not a second transcript.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from core.chat.turn_journal import EVENT_TURN_STEER

TURN_STEER_SCHEMA = "turn_steer.v1"
DELIVERY_GUIDE = "guide"
DELIVERY_QUEUE = "queue"
DISPOSITION_ADMITTED = "admitted"
DISPOSITION_DELIVERY_CHANGED = "delivery_changed"
DISPOSITION_PROMOTED = "promoted"


def _service():
    from core.web.services import session_service

    return session_service


def new_steer_id() -> str:
    return f"steer_{uuid4().hex}"


def _payload(
    *,
    steer_id: str,
    delivery: str,
    disposition: str,
    target_turn_id: str = "",
    from_delivery: str = "",
    content: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": TURN_STEER_SCHEMA,
        "steerId": str(steer_id or "").strip(),
        "delivery": str(delivery or "").strip(),
        "disposition": str(disposition or "").strip(),
    }
    normalized_target = str(target_turn_id or "").strip()
    if normalized_target:
        payload["targetTurnId"] = normalized_target
    normalized_from = str(from_delivery or "").strip()
    if normalized_from:
        payload["fromDelivery"] = normalized_from
    if content is not None and disposition != DISPOSITION_PROMOTED:
        payload["content"] = str(content)
    return payload


def append_turn_steer_event(
    session_id: str,
    turn_id: str,
    payload: dict[str, Any],
    *,
    correlation_id: str = "",
) -> Any | None:
    """Append one out-of-band steer fact. Callers decide whether failure is fatal."""

    s = _service()
    steer_id = str(payload.get("steerId") or "").strip()
    journal_turn_id = str(turn_id or "").strip() or steer_id
    correlation = str(correlation_id or "").strip() or steer_id
    return s._append_session_conversation_event(
        str(session_id or "").strip(),
        journal_turn_id,
        EVENT_TURN_STEER,
        status=str(payload.get("disposition") or "").strip(),
        payload=payload,
        source="turn_steer",
        visible_in_model=False,
        projection_kind="turn_steer",
        correlation_id=correlation,
    )


def record_admitted(
    session_id: str,
    *,
    steer_id: str,
    delivery: str,
    turn_id: str,
    target_turn_id: str = "",
    content: str,
) -> None:
    append_turn_steer_event(
        session_id,
        turn_id,
        _payload(
            steer_id=steer_id,
            delivery=delivery,
            disposition=DISPOSITION_ADMITTED,
            target_turn_id=target_turn_id or turn_id,
            content=content,
        ),
    )


def record_delivery_changed(
    session_id: str,
    *,
    steer_id: str,
    turn_id: str,
    target_turn_id: str,
    content: str,
    from_delivery: str = DELIVERY_GUIDE,
    to_delivery: str = DELIVERY_QUEUE,
) -> None:
    append_turn_steer_event(
        session_id,
        turn_id,
        _payload(
            steer_id=steer_id,
            delivery=to_delivery,
            disposition=DISPOSITION_DELIVERY_CHANGED,
            target_turn_id=target_turn_id,
            from_delivery=from_delivery,
            content=content,
        ),
    )


def record_promoted(
    session_id: str,
    *,
    steer_id: str,
    turn_id: str,
    delivery: str = DELIVERY_QUEUE,
    correlation_id: str = "",
) -> None:
    append_turn_steer_event(
        session_id,
        turn_id,
        _payload(
            steer_id=steer_id,
            delivery=delivery,
            disposition=DISPOSITION_PROMOTED,
            target_turn_id=turn_id,
        ),
        correlation_id=correlation_id,
    )


def retarget_unjournaled_guide(
    session_id: str,
    *,
    steer_id: str,
    turn_id: str,
    content: str,
    lang: str = "",
) -> dict[str, Any] | None:
    """Move a guide that never became a user message onto the next-turn queue."""

    s = _service()
    record_delivery_changed(
        session_id,
        steer_id=steer_id,
        turn_id=turn_id,
        target_turn_id=turn_id,
        content=content,
    )
    return s.enqueue_session_queued_turn(
        session_id,
        content=content,
        attachments=[],
        references=[],
        mental_model_enabled=None,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=None,
        client_submission_id=f"steer:{steer_id}",
        steer_id=steer_id,
        record_steer_admission=False,
        lang=lang,
    )
