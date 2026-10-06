"""Per-turn incremental turnItems projection for assistant_delta publish.

Claim scope: publish-side delta projector state, the per-frame witness snapshot
consumed by the SSE write edge (``stream_transport_delta``), and the projector
registry/cleanup. Authority paths — initial/detail assembly, live overlay
message, checkpoint and busy snapshots, stream re-baseline — keep building
through ``projection.py`` full rebuilds and never read this state.

Defect being fixed: every assistant_delta frame used to rebuild the codex
transcript + turnItems projection from the full accumulated content (O(total)
per frame, O(total²) per turn) and the write edge re-serialized and re-hashed
every item for every connection. The projector keeps the last canonical item
list per turn; when a frame only appends to the streaming text (verified
append-only against the cached projection, with every other projection input
unchanged by signature), it patches only the changed rows and refreshes only
their witnesses. Anything else — boundary frames (stage/done flips), tool,
feedback or journal changes, text rewrites/shrinks, or any cache doubt — falls
back to the full rebuild, which stays the sole authority and is also what
refreshes the incremental cache for the next append run.

The per-frame witness (item fingerprints + text cursors + bounded prefix
history) travels on the event under :data:`WITNESS_FIELD` so queued and
coalesced frames freeze the witness state they were built with; the SSE write
edge strips the field before encoding and it never reaches the wire.

Fingerprint semantics for the write edge are preserved: a connection still
omits an item only when it can prove the client already holds an identical row,
and an append fragment is still only cut when the delivered prefix is verified
against the projector's digest chain (hasher fed append-only). The derivation
of fingerprints changed from "blake2b of the full serialized row" to
"text-digest + non-text-digest" so a growing row costs O(delta) instead of
O(total); fingerprints never leave the process, so only cross-frame equality
matters, which the split preserves exactly.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Mapping

# In-process-only event field carrying the frame witness. Stripped at the SSE
# write edge (stream_transport_delta.compact) before anything is encoded.
WITNESS_FIELD = "_turnItemWitness"

# TurnItem types whose body grows append-only while streaming (mirrors
# stream_transport_delta.TEXT_APPEND_ITEM_TYPES).
_TEXT_APPEND_ITEM_TYPES = {"agent_message", "reasoning"}

# Recent (length -> digest) snapshots kept per text item so a lagging
# connection can verify its delivered prefix against any recent frame. The
# subscriber queue holds far fewer frames than this bound; a miss falls back to
# a full row, never to a guess.
_PREFIX_HISTORY_LIMIT = 64

# Bounded projector registry: entries are removed when their turn publishes a
# terminal frame; the cap covers turns that never settle (crashed workers).
_MAX_PROJECTORS = 32

_LOCK = threading.Lock()
_PROJECTORS: dict[tuple[str, str], "TurnDeltaProjector"] = {}


def _service():
    from core.web.services import session_service

    return session_service


@dataclass(frozen=True)
class AssistantDeltaFrameWitness:
    """Immutable per-frame witness snapshot consumed by the SSE write edge."""

    fingerprints: Mapping[tuple[str, str], bytes]
    text_cursors: Mapping[tuple[str, str], tuple[int, bytes]]
    prefix_history: Mapping[tuple[str, str], Mapping[int, bytes]]


class _TextWitness:
    """Append-only blake2b chain for one text-bearing item.

    ``digest`` equals ``blake2b(full_text)`` at every point in time, but is
    maintained in O(delta) per frame; history records the digest at every
    length the text passed through so a connection can prove its cached prefix
    without re-hashing the body.
    """

    __slots__ = ("hasher", "length", "history")

    def __init__(self, text: str) -> None:
        self.hasher = hashlib.blake2b(text.encode("utf-8"), digest_size=16)
        self.length = len(text)
        self.history: dict[int, bytes] = {self.length: self.hasher.digest()}

    def append(self, appended: str) -> None:
        if not appended:
            return
        self.hasher.update(appended.encode("utf-8"))
        self.length += len(appended)
        self.history[self.length] = self.hasher.digest()
        while len(self.history) > _PREFIX_HISTORY_LIMIT:
            self.history.pop(next(iter(self.history)))

    @property
    def digest(self) -> bytes:
        return self.hasher.digest()


def item_identity(item: Mapping[str, Any]) -> tuple[str, str] | None:
    """Match the write edge's canonicalItemIdentity, including call identity."""

    if not isinstance(item, Mapping):
        return None
    if str(item.get("type") or "") == "tool_call":
        call_id = str(item.get("callId") or "").strip()
        return ("call", call_id) if call_id else None
    item_id = str(item.get("itemId") or "").strip()
    return ("item", item_id) if item_id else None


def _non_text_digest(item: Mapping[str, Any]) -> bytes:
    payload = {key: value for key, value in item.items() if key != "text"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).digest()


def _full_item_digest(item: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).digest()


def _tail_signature(value: Any) -> tuple[int, str]:
    text = value if isinstance(value, str) else str(value or "")
    return (len(text), text[-64:])


def _feedback_events_signature(events: Any) -> tuple:
    """Shallow content signature over live feedback events.

    The capture mutates the running thought event in place, so object identity
    cannot witness changes; length + tail covers append growth and same-length
    tail rewrites at O(events) per frame instead of O(preview bytes).
    """

    if not isinstance(events, list):
        events = []
    parts: list[tuple] = []
    for event in events:
        if not isinstance(event, dict):
            parts.append(("?",))
            continue
        parts.append(
            (
                str(event.get("kind") or ""),
                str(event.get("status") or ""),
                int(event.get("sequence") or 0),
                int(event.get("revision") or 0),
                _tail_signature(event.get("resultPreview")),
                _tail_signature(event.get("summary")),
            )
        )
    return (len(parts), tuple(parts))


def _tool_calls_signature(tool_calls: Any) -> tuple:
    if not isinstance(tool_calls, list):
        tool_calls = []
    parts: list[tuple] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            parts.append(("?",))
            continue
        parts.append(
            (
                str(call.get("id") or call.get("callId") or ""),
                str(call.get("name") or call.get("toolName") or ""),
                str(call.get("status") or ""),
                _tail_signature(call.get("input")),
                _tail_signature(call.get("output")),
                _tail_signature(call.get("result")),
            )
        )
    return (len(parts), tuple(parts))


def _mental_snapshot_signature(mental_snapshot: Any) -> tuple:
    if not isinstance(mental_snapshot, Mapping):
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in mental_snapshot.items()))[:64]


def _carrier_extendable(item: Mapping[str, Any], *, journal_has_turn_items: bool) -> bool:
    """Mirror the live-merge extendability rules onto canonical v3 rows.

    v3 canonicalization drops ``provisional``, so extendability is judged from
    status plus journal presence: a running row is a live streaming row; a
    completed row is only the authority-extendable live shape when the journal
    had no turn items at rebuild time (journal rows commit as completed and
    the authority merges never extend them).
    """

    status = str(item.get("status") or "").strip().lower()
    if status in {"", "pending", "running"}:
        return True
    return status == "completed" and not journal_has_turn_items


class TurnDeltaProjector:
    """Per-(session, turn) incremental turnItems projection state.

    ``mode`` records how the last frame was produced ("incremental" or
    "rebuild") for publish telemetry.
    """

    def __init__(self, session_id: str, turn_id: str) -> None:
        self.session_id = str(session_id or "").strip()
        self.turn_id = str(turn_id or "").strip()
        self.mode = "rebuild"
        self.last_frame_witness_bytes = 0
        self._items: list[dict[str, Any]] | None = None
        self._content = ""
        self._thought = ""
        self._source_sig: tuple | None = None
        self._fingerprints: dict[tuple[str, str], bytes] = {}
        self._text_witnesses: dict[tuple[str, str], _TextWitness] = {}
        self._non_text_digests: dict[tuple[str, str], bytes] = {}
        self._content_carrier: tuple[int, tuple[str, str]] | None = None
        self._thought_carrier: tuple[int, tuple[str, str]] | None = None

    # -- public entry -----------------------------------------------------

    def frame_items(
        self,
        *,
        message_id: str,
        content: Any,
        thought: Any,
        feedback_events: Any,
        tool_calls: Any,
        mental_snapshot: Any,
        stage: Any,
        done: bool,
        ledger_sequence: int,
        service: Any = None,
    ) -> tuple[list[dict[str, Any]], AssistantDeltaFrameWitness]:
        """Return canonical turnItems plus the frame witness.

        Fast path: patch cached rows when the frame only appends text and every
        other projection input is unchanged. Everything else rebuilds through
        the authority projection and refreshes the cache. ``service`` is the
        caller-resolved facade so publish-level patches stay authoritative for
        the rebuild path too.
        """

        content_text = str(content or "")
        thought_text = str(thought or "")
        source_sig = (
            str(message_id or "").strip(),
            str(stage or "").strip(),
            bool(done),
            int(ledger_sequence or 0),
            _feedback_events_signature(feedback_events),
            _tool_calls_signature(tool_calls),
            _mental_snapshot_signature(mental_snapshot),
        )
        self.last_frame_witness_bytes = 0

        patch = self._incremental_patch(
            content_text,
            thought_text,
            source_sig,
        )
        if patch is not None:
            items = patch
            self.mode = "incremental"
        else:
            # Record the frame's projected text before rebuilding: carrier
            # detection inside _rebuild matches rows against these values.
            self._content = content_text
            self._thought = thought_text
            items = self._rebuild(
                message_id=message_id,
                content=content_text,
                thought=thought_text,
                feedback_events=feedback_events,
                tool_calls=tool_calls,
                mental_snapshot=mental_snapshot,
                stage=stage,
                done=done,
                service=service,
            )
            self._source_sig = source_sig
            self.mode = "rebuild"
        return self._items or [], self._frame_witness()

    # -- incremental fast path --------------------------------------------

    def _incremental_patch(
        self,
        content_text: str,
        thought_text: str,
        source_sig: tuple,
    ) -> list[dict[str, Any]] | None:
        if self._items is None or self._source_sig is None or self._source_sig != source_sig:
            return None
        if not content_text.startswith(self._content) or not thought_text.startswith(self._thought):
            return None
        content_appended = content_text[len(self._content):]
        thought_appended = thought_text[len(self._thought):]
        if content_appended and self._content_carrier is None:
            return None
        if thought_appended and self._thought_carrier is None:
            return None
        items = self._items
        if content_appended:
            items = self._patch_carrier(items, self._content_carrier, content_text, content_appended, self._content)
            if items is None:
                return None
        if thought_appended:
            items = self._patch_carrier(items, self._thought_carrier, thought_text, thought_appended, self._thought)
            if items is None:
                return None
        self._content = content_text
        self._thought = thought_text
        self._items = items
        return items

    def _patch_carrier(
        self,
        items: list[dict[str, Any]],
        carrier: tuple[int, tuple[str, str]],
        text: str,
        appended: str,
        cached_text: str,
    ) -> list[dict[str, Any]] | None:
        index, identity = carrier
        if not 0 <= index < len(items):
            return None
        source = items[index]
        if not isinstance(source, dict) or item_identity(source) != identity:
            return None
        # The carrier row must be exactly the row the cached text mapped onto;
        # any drift falls back to the authority rebuild.
        if str(source.get("text") or "") != cached_text:
            return None
        witness = self._text_witnesses.get(identity)
        non_text = self._non_text_digests.get(identity)
        if witness is None or non_text is None:
            return None
        patched = dict(source)
        patched["text"] = text
        witness.append(appended)
        self._fingerprints[identity] = witness.digest + non_text
        self.last_frame_witness_bytes += len(appended.encode("utf-8"))
        if items is self._items:
            items = list(items)
        items[index] = patched
        return items

    # -- authority rebuild -------------------------------------------------

    def _rebuild(
        self,
        *,
        message_id: str,
        content: str,
        thought: str,
        feedback_events: Any,
        tool_calls: Any,
        mental_snapshot: Any,
        stage: Any,
        done: bool,
        service: Any = None,
    ) -> list[dict[str, Any]]:
        s = service if service is not None else _service()
        codex_transcript = s._build_codex_transcript_projection(
            message_id=message_id,
            content=content,
            feedback_events=feedback_events,
            tool_calls=tool_calls,
            streaming=not done,
        )
        items = s._build_session_turn_items_projection(
            session_id=self.session_id,
            turn_id=self.turn_id,
            message_id=message_id,
            content=content,
            thought=thought,
            mental_snapshot=mental_snapshot,
            codex_transcript=codex_transcript,
            done=done,
            source="assistant_delta",
            stage=stage,
        )
        self._items = list(items)
        self._refresh_witnesses(self._items)
        self._record_carriers(self._items, journal_has_turn_items=self._journal_has_turn_items(s))
        return self._items

    def _refresh_witnesses(self, items: list[dict[str, Any]]) -> None:
        self._fingerprints = {}
        self._text_witnesses = {}
        self._non_text_digests = {}
        self.last_frame_witness_bytes = 0
        for item in items:
            identity = item_identity(item)
            if identity is None:
                continue
            if str(item.get("type") or "") in _TEXT_APPEND_ITEM_TYPES and isinstance(item.get("text"), str):
                witness = _TextWitness(item["text"])
                non_text = _non_text_digest(item)
                self._text_witnesses[identity] = witness
                self._non_text_digests[identity] = non_text
                self._fingerprints[identity] = witness.digest + non_text
                self.last_frame_witness_bytes += len(item["text"].encode("utf-8")) + 16
            else:
                self._fingerprints[identity] = _full_item_digest(item)
                self.last_frame_witness_bytes += 16

    def _journal_has_turn_items(self, service: Any) -> bool:
        """Whether the journal already carries canonical items for this turn.

        Mirrors the journal-source check the authority projection performs.
        Any failure resolves conservatively to True (carriers rejected, frames
        rebuild), never to a permissive guess.
        """

        try:
            events = service._load_session_conversation_events_cached(self.session_id)
            return bool(
                service.conversation_turn_items_from_events(
                    events,
                    turn_id=self.turn_id,
                )
            )
        except Exception:
            return True

    def _record_carriers(self, items: list[dict[str, Any]], *, journal_has_turn_items: bool) -> None:
        self._content_carrier = None
        self._thought_carrier = None
        if not self._content and not self._thought:
            return
        for index, item in enumerate(items):
            identity = item_identity(item)
            if identity is None or not isinstance(item.get("text"), str):
                continue
            text = item["text"]
            item_type = str(item.get("type") or "")
            if (
                self._content
                and self._content_carrier is None
                and text == self._content
                and item_type == "agent_message"
                and str(item.get("phase") or "") == "final_answer"
                and _carrier_extendable(item, journal_has_turn_items=journal_has_turn_items)
            ):
                self._content_carrier = (index, identity)
            if (
                self._thought
                and self._thought_carrier is None
                and text == self._thought
                and item_type == "reasoning"
                and _carrier_extendable(item, journal_has_turn_items=journal_has_turn_items)
            ):
                self._thought_carrier = (index, identity)

    # -- witness snapshot ---------------------------------------------------

    def _frame_witness(self) -> AssistantDeltaFrameWitness:
        return AssistantDeltaFrameWitness(
            fingerprints=dict(self._fingerprints),
            text_cursors={
                identity: (witness.length, witness.digest)
                for identity, witness in self._text_witnesses.items()
            },
            prefix_history={
                identity: dict(witness.history)
                for identity, witness in self._text_witnesses.items()
            },
        )


def turn_delta_projector(session_id: str, turn_id: str) -> TurnDeltaProjector | None:
    """Return the per-turn projector, creating it on first use.

    Returns ``None`` when the frame has no turn identity to cache against;
    those frames keep the legacy full-rebuild publish path.
    """

    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    if not normalized_session_id or not normalized_turn_id:
        return None
    key = (normalized_session_id, normalized_turn_id)
    with _LOCK:
        projector = _PROJECTORS.get(key)
        if projector is None:
            projector = TurnDeltaProjector(normalized_session_id, normalized_turn_id)
            _PROJECTORS[key] = projector
            while len(_PROJECTORS) > _MAX_PROJECTORS:
                oldest = next(iter(_PROJECTORS))
                _PROJECTORS.pop(oldest, None)
        return projector


def drop_turn_delta_projector(session_id: str, turn_id: str) -> None:
    """Drop the projector when its turn publishes a terminal frame."""

    key = (str(session_id or "").strip(), str(turn_id or "").strip())
    with _LOCK:
        _PROJECTORS.pop(key, None)


def reset_turn_delta_projectors_for_tests() -> None:
    with _LOCK:
        _PROJECTORS.clear()
