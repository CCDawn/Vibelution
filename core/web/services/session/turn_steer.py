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
Drain receipts reference the existing user event and locate its display boundary.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from core.chat.turn_journal import EVENT_TURN_STEER, EVENT_USER_MESSAGE, TERMINAL_EVENTS

TURN_STEER_SCHEMA = "turn_steer.v1"
DELIVERY_GUIDE = "guide"
DELIVERY_QUEUE = "queue"
DISPOSITION_ADMITTED = "admitted"
DISPOSITION_DELIVERY_CHANGED = "delivery_changed"
DISPOSITION_PROMOTED = "promoted"
DISPOSITION_DRAINED = "drained"
DISPOSITION_DISPLAY_ITEM_STARTED = "display_item_started"
DISPOSITION_DISPLAY_CONTENT_REBASED = "display_content_rebased"
_GUIDANCE_KINDS = frozenset({"user_guidance", "user_interrupt_guidance"})


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


def _sequence(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def record_display_item_started(
    session_id: str,
    turn_id: str,
    *,
    item_id: str,
    kind: str,
    projection_item_id: str = "",
    call_id: str = "",
    content_offset: int = 0,
) -> Any | None:
    """Record an output item's first appearance, without storing its content."""
    payload = _payload(
        steer_id=f"display:{item_id}", delivery="display",
        disposition=DISPOSITION_DISPLAY_ITEM_STARTED, target_turn_id=turn_id,
    )
    payload.update(itemId=item_id, kind=kind)
    if projection_item_id:
        payload["projectionItemId"] = projection_item_id
    if call_id:
        payload["callId"] = call_id
    if kind == "agent_message":
        payload["contentOffset"] = max(0, content_offset)
    return append_turn_steer_event(session_id, turn_id, payload, correlation_id=item_id)


def record_display_content_rebased(session_id: str, turn_id: str, *, item_id: str) -> Any | None:
    """Mark a live capture replacement; its immutable creation order is unchanged."""
    payload = _payload(
        steer_id=f"display:{item_id}", delivery="display",
        disposition=DISPOSITION_DISPLAY_CONTENT_REBASED, target_turn_id=turn_id,
    )
    payload.update(itemId=item_id, contentOffset=0)
    return append_turn_steer_event(session_id, turn_id, payload, correlation_id=item_id)


def display_item_order_provenance(events: Any, turn_id: str) -> dict[str, dict[str, Any]]:
    """Derive immutable creation positions from the active Journal path.

    Old items have their first commit/start as the available historical order.
    New stream items have an explicit creation fact before any content is shown.
    """
    from core.chat.turn_journal import fold_active_events

    result: dict[str, dict[str, Any]] = {}
    call_orders: dict[str, int] = {}
    anchors: list[Any] = []
    for event in fold_active_events(sorted(events or [], key=lambda row: _sequence(getattr(row, "sequence", 0)))):
        if str(getattr(event, "turn_id", "") or "").strip() != turn_id:
            continue
        payload = dict(getattr(event, "payload", None) or {})
        sequence = _sequence(getattr(event, "sequence", 0))
        if event.event_type == "tool_call_started":
            tool = dict(payload.get("toolCall") or {})
            call_id = str(tool.get("callId") or tool.get("toolCallId") or event.tool_call_id or "").strip()
            if call_id:
                call_orders.setdefault(call_id, sequence)
        elif event.event_type == "assistant_item_committed":
            item_id = str(payload.get("itemId") or "").strip()
            if item_id:
                result.setdefault(item_id, {"itemId": item_id, "orderSequence": sequence})
                call_id = str(payload.get("callId") or "").strip()
                if call_id:
                    result[item_id]["callId"] = call_id
        elif event.event_type == EVENT_TURN_STEER and payload.get("disposition") in {
            DISPOSITION_DISPLAY_ITEM_STARTED, DISPOSITION_DISPLAY_CONTENT_REBASED,
        }:
            anchors.append(event)
    for item_id, record in result.items():
        if record.get("callId") in call_orders:
            record["orderSequence"] = min(record["orderSequence"], call_orders[record["callId"]])
    for event in anchors:
        payload = dict(event.payload or {})
        item_id = str(payload.get("itemId") or "").strip()
        if not item_id:
            continue
        if payload.get("disposition") == DISPOSITION_DISPLAY_CONTENT_REBASED:
            if item_id in result:
                result[item_id]["contentOffset"] = 0
            continue
        record = result.setdefault(item_id, {"itemId": item_id, "orderSequence": event.sequence})
        record["orderSequence"] = min(record["orderSequence"], event.sequence)
        record.setdefault("kind", str(payload.get("kind") or ""))
        record.setdefault("contentOffset", _sequence(payload.get("contentOffset")))
        alias = str(payload.get("projectionItemId") or "").strip()
        if alias:
            result[alias] = record
        call_id = str(payload.get("callId") or "").strip()
        if call_id:
            result[f"call:{call_id}"] = record
        result[f"latest:{record['kind']}"] = record
    for call_id, sequence in call_orders.items():
        result.setdefault(f"call:{call_id}", {"orderSequence": sequence})
    return result


def guidance_metadata_from_events(events: Any) -> dict[str, dict[str, Any]]:
    """Read display-only guidance identity and the first reliable drain boundary.

    A drain is the host handing text to the Agent, not evidence that a provider
    request succeeded. Missing receipts after settlement remain unconfirmed;
    historical turns and failed receipt writes cannot establish consumption.
    """
    event_list = list(events or [])
    guides: dict[str, Any] = {}
    terminal_turn_ids: set[str] = set()
    for event in event_list:
        event_type = str(getattr(event, "event_type", "") or "")
        if event_type in TERMINAL_EVENTS:
            terminal_turn_ids.add(str(getattr(event, "turn_id", "") or "").strip())
        if event_type != EVENT_USER_MESSAGE:
            continue
        payload = dict(getattr(event, "payload", None) or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        event_id = str(getattr(event, "event_id", "") or "").strip()
        if str(metadata.get("kind") or "").strip() in _GUIDANCE_KINDS and event_id:
            guides[event_id] = event
    result = {
        event_id: {
            "guidanceEventId": event_id,
            "guidanceSequence": _sequence(getattr(event, "sequence", 0)),
            "guidanceState": (
                "unconfirmed" if str(getattr(event, "turn_id", "") or "").strip() in terminal_turn_ids
                else "pending"
            ),
        }
        for event_id, event in guides.items()
    }
    for event in event_list:
        if str(getattr(event, "event_type", "") or "") != EVENT_TURN_STEER:
            continue
        payload = dict(getattr(event, "payload", None) or {})
        if payload.get("disposition") != DISPOSITION_DRAINED or payload.get("delivery") != DELIVERY_GUIDE:
            continue
        user_event_id = str(payload.get("userMessageEventId") or "").strip()
        guide = guides.get(user_event_id)
        if guide is None:
            continue
        turn_id = str(getattr(guide, "turn_id", "") or "").strip()
        guide_sequence = _sequence(getattr(guide, "sequence", 0))
        receipt_sequence = _sequence(getattr(event, "sequence", 0))
        if (
            not turn_id
            or str(getattr(event, "turn_id", "") or "").strip() != turn_id
            or str(payload.get("targetTurnId") or turn_id).strip() != turn_id
            or _sequence(payload.get("userMessageSequence")) != guide_sequence
            or receipt_sequence <= guide_sequence
        ):
            continue
        previous_sequence = result[user_event_id].get("guidanceConsumedSequence")
        if previous_sequence is not None and previous_sequence <= receipt_sequence:
            continue
        result[user_event_id].update(
            guidanceState="drained",
            guidanceConsumedSequence=receipt_sequence,
        )
    return result


def restore_guidance_display_messages(messages: list[dict[str, Any]], events: Any) -> list[dict[str, Any]]:
    """Restore distinct guidance rows lost by model replay's content dedup.

    This is a read-only detail projection from the same Journal. Ordinary user
    dedup and model replay remain unchanged; only active-branch guidance returns.
    Run before pagination so windows and refresh use the same message identities.
    """
    event_list = list(events or [])
    displayed_ids = {
        str((message.get("metadata") or {}).get("eventId") or "").strip()
        for message in messages
    }
    missing: set[str] = set()
    for event in event_list:
        if str(getattr(event, "event_type", "") or "") != EVENT_USER_MESSAGE:
            continue
        payload = dict(getattr(event, "payload", None) or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        event_id = str(getattr(event, "event_id", "") or "").strip()
        if (
            event_id and event_id not in displayed_ids
            and str(metadata.get("kind") or "").strip() in _GUIDANCE_KINDS
            and str(payload.get("content") or "").strip()
            and getattr(event, "visible_in_model", True)
        ):
            missing.add(event_id)
    if not missing:
        return messages
    from core.chat.turn_journal import fold_active_events

    restored: list[tuple[int, dict[str, Any]]] = []
    for event in fold_active_events(event_list):
        if event.event_id not in missing:
            continue
        payload = dict(event.payload or {})
        metadata = dict(payload.get("metadata") or {})
        restored.append((event.sequence, {
            "role": "user",
            "content": str(payload.get("content") or "").strip(),
            "timestamp": event.timestamp,
            "attachments": list(payload.get("attachments") or []),
            "references": list(payload.get("references") or []),
            "metadata": {**metadata, "turnId": event.turn_id, "eventId": event.event_id},
        }))
    if not restored:
        return messages
    sequences = {event.event_id: event.sequence for event in event_list}
    result: list[dict[str, Any]] = []
    pending = iter(sorted(restored, key=lambda row: row[0]))
    next_row = next(pending, None)
    for message in messages:
        sequence = sequences.get(str((message.get("metadata") or {}).get("eventId") or ""), 0)
        while next_row is not None and sequence > next_row[0]:
            result.append(next_row[1])
            next_row = next(pending, None)
        result.append(message)
    while next_row is not None:
        result.append(next_row[1])
        next_row = next(pending, None)
    return result


def drain_guidance_events(
    session_id: str,
    turn_id: str,
    events: Any,
    consumed_keys: set[str],
) -> list[str]:
    """Drain same-turn guidance while preserving its first durable UI boundary.

    Only the worker-local keys suppress model injection. A new worker can need
    the text again, while an existing receipt must keep its original sequence.
    Receipt failure never drops guidance that the existing provider could deliver.
    """
    event_list = list(events or [])
    receipt_metadata: dict[str, dict[str, Any]] | None = None
    guides: list[Any] = []
    for event in event_list:
        if (
            str(getattr(event, "event_type", "") or "") != EVENT_USER_MESSAGE
            or str(getattr(event, "turn_id", "") or "").strip() != turn_id
        ):
            continue
        payload = dict(getattr(event, "payload", None) or {})
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if str(metadata.get("kind") or "").strip() in _GUIDANCE_KINDS:
            guides.append(event)
    pending: list[str] = []
    # Every unconsumed submission must reach the next request. A tail window
    # silently loses the oldest input when more than eight arrive between polls.
    for event in sorted(guides, key=lambda item: _sequence(getattr(item, "sequence", 0))):
        payload = dict(getattr(event, "payload", None) or {})
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        event_id = str(getattr(event, "event_id", "") or "").strip()
        sequence = _sequence(getattr(event, "sequence", 0))
        key = event_id or (f"seq:{sequence}" if sequence else f"text:{content}")
        if key in consumed_keys:
            continue
        consumed_keys.add(key)
        if receipt_metadata is None:
            receipt_metadata = guidance_metadata_from_events(event_list)
        if event_id and sequence and receipt_metadata.get(event_id, {}).get("guidanceState") != "drained":
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            receipt = _payload(
                steer_id=str(metadata.get("steerId") or event_id).strip(),
                delivery=DELIVERY_GUIDE,
                disposition=DISPOSITION_DRAINED,
                target_turn_id=turn_id,
            )
            receipt.update(userMessageEventId=event_id, userMessageSequence=sequence)
            try:
                append_turn_steer_event(session_id, turn_id, receipt, correlation_id=event_id)
            except Exception:
                # The journal bridge records the write failure. This auxiliary
                # fact must not turn a working guidance path into dropped input.
                pass
        pending.append(content)
    return pending


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
