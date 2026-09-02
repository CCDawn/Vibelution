"""Chat-room speaker delta capture (answer-only streaming for room SSE).

Claim scope: chat-room-only ContextVar capture of assistant visible answer
deltas plus per-turn ticket invalidation, fanned out through the chat-room
stream subscribers in ``chat_room_service``.

This module never touches the direct-chat Session live output contract: it
does not write ``_SESSION_LIVE_OUTPUTS``, the Session Journal, or any
Session SSE surface.  The UI proxy here is layered *on top of* the session
capture hooks (``session.stream_capture._ensure_session_ui_capture_hooks``)
without modifying that module: both installation orders keep the direct-chat
capture working, because the chat-room layer is gated by its own ContextVar
and the direct-chat layer keeps its own.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextlib import nullcontext
from contextvars import ContextVar
from typing import Any, Callable

# Explicit kill switch for the MVP fan-out.  Flip to False to disable every
# chat-room speaker delta without touching the round engine.
CHAT_ROOM_SPEAKER_DELTA_ENABLED = True

# Answer-only MVP: thought/reasoning deltas are intentionally not forwarded.
CHAT_ROOM_SPEAKER_DELTA_STAGE = "answer"

# Batching cadence aligned with the direct-chat UI capture batcher
# (session.stream_capture *_MAX_LATENCY_SECONDS = 0.12).
CHAT_ROOM_SPEAKER_DELTA_MIN_INTERVAL_SECONDS = 0.12

_EVENT_TYPE = "chat_room_speaker_delta"
_RUNNING_STATUS = "running"
_TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped", "aborted"})

_CHAT_ROOM_CAPTURE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_chat_room_speaker_capture_context",
    default={},
)

# Guards only the chat-room proxy installation; the direct-chat wrap keeps
# its own lock inside session.stream_capture (never acquired here).
_CHAT_ROOM_CAPTURE_WRAP_LOCK = threading.Lock()

_PUBLISH_SINK: Callable[[dict[str, Any]], None] | None = None
_PUBLISH_SINK_LOCK = threading.Lock()


def set_delta_publisher(publisher: Callable[[dict[str, Any]], None] | None) -> None:
    """Register the fan-out sink (chat_room_service owns the subscribers)."""

    global _PUBLISH_SINK
    with _PUBLISH_SINK_LOCK:
        _PUBLISH_SINK = publisher


def _sink() -> Callable[[dict[str, Any]], None] | None:
    with _PUBLISH_SINK_LOCK:
        publisher = _PUBLISH_SINK
    if publisher is not None:
        return publisher

    # Late-bound fallback so tests / embedders work without explicit wiring.
    from core.web.services import chat_room_service

    publisher = getattr(chat_room_service, "_publish_chat_room_speaker_delta", None)
    return publisher if callable(publisher) else None


class _SpeakerDeltaTicket:
    """Per-turn validity token plus accumulated answer state."""

    __slots__ = (
        "room_id",
        "round_id",
        "participant_id",
        "session_id",
        "turn_id",
        "lock",
        "closed",
        "content",
        "seq",
        "last_publish_monotonic",
    )

    def __init__(
        self,
        *,
        room_id: str,
        round_id: str,
        participant_id: str,
        session_id: str,
        turn_id: str,
    ) -> None:
        self.room_id = room_id
        self.round_id = round_id
        self.participant_id = participant_id
        self.session_id = session_id
        self.turn_id = turn_id
        self.lock = threading.Lock()
        self.closed = False
        self.content = ""
        self.seq = 0
        self.last_publish_monotonic = 0.0


_TICKETS_LOCK = threading.Lock()
_TICKETS: dict[tuple[str, str], _SpeakerDeltaTicket] = {}


def _ticket_key(round_id: str, participant_id: str) -> tuple[str, str]:
    return (str(round_id or "").strip(), str(participant_id or "").strip())


def _build_event(
    ticket: _SpeakerDeltaTicket,
    *,
    seq: int,
    content: str,
    done: bool,
    status: str,
) -> dict[str, Any]:
    return {
        "type": _EVENT_TYPE,
        "roomId": ticket.room_id,
        "roundId": ticket.round_id,
        "participantId": ticket.participant_id,
        "sessionId": ticket.session_id,
        "turnId": ticket.turn_id,
        "seq": int(seq),
        "stage": CHAT_ROOM_SPEAKER_DELTA_STAGE,
        "content": content,
        "done": bool(done),
        "status": status,
    }


def _publish_event(event: dict[str, Any]) -> None:
    publisher = _sink()
    if publisher is None:
        return
    try:
        publisher(event)
    except Exception:
        # Delta delivery must never break the speaker turn; the next
        # snapshot (authoritative) still reaches every subscriber.
        return


def _observe_stream_response(text: str, done: bool) -> None:
    """UI-proxy observer: accumulate the answer and publish a delta frame."""

    context = _CHAT_ROOM_CAPTURE_CONTEXT.get({})
    ticket = context.get("ticket") if isinstance(context, dict) else None
    if not isinstance(ticket, _SpeakerDeltaTicket):
        return
    cleaned = str(text or "")
    if not cleaned and not done:
        return
    now = time.monotonic()
    publish = False
    event: dict[str, Any] | None = None
    with ticket.lock:
        if ticket.closed:
            # Late delta from a watchdog-abandoned thread: dropped here.
            return
        previous = ticket.content
        if done:
            next_content = cleaned
        elif previous and cleaned.startswith(previous):
            next_content = cleaned
        else:
            next_content = f"{previous}{cleaned}" if previous else cleaned
        ticket.content = next_content
        if not done and (now - ticket.last_publish_monotonic) < (
            CHAT_ROOM_SPEAKER_DELTA_MIN_INTERVAL_SECONDS
        ):
            return
        ticket.last_publish_monotonic = now
        ticket.seq += 1
        event = _build_event(
            ticket,
            seq=ticket.seq,
            content=next_content,
            done=bool(done),
            status=_RUNNING_STATUS,
        )
        publish = True
    if publish and event is not None:
        _publish_event(event)


def close_speaker_delta(*, round_id: str, participant_id: str, status: str) -> None:
    """Invalidate the per-turn ticket and emit one terminal delta frame.

    Idempotent: only the first closer transitions the ticket and publishes
    the terminal frame.  Callers use this for watchdog abandonment
    (``status="aborted"``), round stop (``"stopped"``), runner failure
    (``"failed"``) and normal completion (``"completed"``).
    """

    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _TERMINAL_STATUSES:
        normalized_status = "failed"
    key = _ticket_key(round_id, participant_id)
    with _TICKETS_LOCK:
        ticket = _TICKETS.get(key)
    if not isinstance(ticket, _SpeakerDeltaTicket):
        return
    event: dict[str, Any] | None = None
    with ticket.lock:
        if ticket.closed:
            return
        ticket.closed = True
        ticket.seq += 1
        event = _build_event(
            ticket,
            seq=ticket.seq,
            content=ticket.content,
            done=True,
            status=normalized_status,
        )
    if event is not None:
        _publish_event(event)
    with _TICKETS_LOCK:
        if _TICKETS.get(key) is ticket:
            _TICKETS.pop(key, None)


def _install_chat_room_proxy_on_ui(ui: Any) -> None:
    """Layer the chat-room proxy onto one UI instance (idempotent)."""

    if bool(getattr(ui, "_vibelution_chat_room_capture_wrapped", False)):
        return
    with _CHAT_ROOM_CAPTURE_WRAP_LOCK:
        if bool(getattr(ui, "_vibelution_chat_room_capture_wrapped", False)):
            return
        previous = getattr(ui, "stream_response", None)

        def chat_room_stream_response_proxy(text: str, done: bool = False):
            if callable(previous):
                previous(text, done=done)
            _observe_stream_response(text, done)

        setattr(ui, "stream_response", chat_room_stream_response_proxy)
        setattr(ui, "_vibelution_chat_room_stream_capture_original", previous)
        setattr(ui, "_vibelution_chat_room_capture_wrapped", True)


def _ensure_chat_room_ui_capture_proxy(ui: Any | None = None) -> None:
    """Idempotently layer the chat-room proxy over the session capture hooks.

    ``_ensure_session_ui_capture_hooks`` runs first so the direct-chat layer
    exists in either installation order; the chat-room proxy then wraps
    whatever ``stream_response`` is currently installed.  Both orders keep
    the direct-chat capture intact because it is gated by its own ContextVar.
    """

    from core.web.services.session import stream_capture as session_stream_capture

    if ui is None:
        from core.ui import get_ui

        ui = get_ui()
    try:
        session_stream_capture._ensure_session_ui_capture_hooks(ui)
    except Exception:
        # The direct-chat layer is optional for the chat-room fan-out.
        pass
    _install_chat_room_proxy_on_ui(ui)


@contextmanager
def speaker_delta_capture(
    *,
    room_id: str,
    round_id: str,
    participant_id: str,
    session_id: str,
    turn_id: str,
    enabled: bool = True,
):
    """Capture one speaker turn's answer deltas into chat-room SSE frames.

    Yields the ticket (or ``None`` when disabled).  The caller remains
    responsible for terminal frames via :func:`close_speaker_delta`; the
    context exit only guarantees ContextVar/table hygiene.
    """

    if not (CHAT_ROOM_SPEAKER_DELTA_ENABLED and enabled):
        yield None
        return
    _ensure_chat_room_ui_capture_proxy()
    ticket = _SpeakerDeltaTicket(
        room_id=str(room_id or "").strip(),
        round_id=str(round_id or "").strip(),
        participant_id=str(participant_id or "").strip(),
        session_id=str(session_id or "").strip(),
        turn_id=str(turn_id or "").strip(),
    )
    key = _ticket_key(ticket.round_id, ticket.participant_id)
    with _TICKETS_LOCK:
        _TICKETS[key] = ticket
    token = _CHAT_ROOM_CAPTURE_CONTEXT.set({"ticket": ticket})
    try:
        yield ticket
    finally:
        _CHAT_ROOM_CAPTURE_CONTEXT.reset(token)
        # Keep the ticket reachable for the caller's terminal frame when the
        # turn exits abnormally (stop/interrupt) before close_speaker_delta
        # ran: the caller closes it after the runner unwinds.  A closed
        # ticket is already removed by its closer.
        with _TICKETS_LOCK:
            if _TICKETS.get(key) is ticket and ticket.closed:
                _TICKETS.pop(key, None)


def speaker_delta_context_for_tests() -> ContextVar:
    """Expose the ContextVar for isolation unit tests only."""

    return _CHAT_ROOM_CAPTURE_CONTEXT


def disabled_capture():
    """Null object mirroring :func:`speaker_delta_capture` when disabled."""

    return nullcontext()


__all__ = [
    "CHAT_ROOM_SPEAKER_DELTA_ENABLED",
    "CHAT_ROOM_SPEAKER_DELTA_MIN_INTERVAL_SECONDS",
    "CHAT_ROOM_SPEAKER_DELTA_STAGE",
    "close_speaker_delta",
    "disabled_capture",
    "set_delta_publisher",
    "speaker_delta_capture",
    "speaker_delta_context_for_tests",
]
