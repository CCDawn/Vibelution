"""Connection-local compression of cumulative TurnItems at the SSE write edge.

Queues and recovery keep full snapshots. Only a consumer that has already sent
an identical item may omit it; reconnecting consumers always start from full.

Text-bearing items (``agent_message`` / ``reasoning``) additionally travel as
append-only fragments: a frame whose text verifiably extends the text last
delivered on this connection carries ``turnItemAppends`` entries
(``kind:"append"`` + ``baseLength``) instead of re-sending the accumulated
body, removing the O(total length) resends that made long turns quadratic on
the wire. Extension is verified against a digest of the sent text (the server
never keeps the body), and the full item snapshot stays the authority: any
rewrite, shrink, first send, terminal frame, or canonical-shape anomaly falls
back to the full row. Consumers validate every append against their cached
length before splicing and fall back to a snapshot on mismatch.

Frames published through the incremental projector carry a
:class:`~core.web.services.session.stream_projection_delta.AssistantDeltaFrameWitness`
under :data:`WITNESS_FIELD` (in-process only, stripped before encoding): the
per-item fingerprints and text cursors were already maintained in O(delta) at
publish time, so ``compact`` reuses them instead of re-serializing and
re-hashing every row per connection. Frames without a witness (legacy
publishers, fixtures) keep the original recompute path.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .stream_projection_delta import WITNESS_FIELD, AssistantDeltaFrameWitness

# TurnItem types whose body grows append-only while streaming. Everything else
# (tool_call/status/retry/error) keeps whole-row snapshots.
TEXT_APPEND_ITEM_TYPES = {"agent_message", "reasoning"}

# Discriminator on append entries; the event-level marker is the presence of
# ``turnItemAppends`` itself plus ``streamEncoding`` on frames that use it.
APPEND_ENTRY_KIND = "append"
STREAM_ENCODING_APPEND = "append-v1"


def _item_text(item: dict[str, Any]) -> str:
    text = item.get("text")
    return text if isinstance(text, str) else ""


def _text_cursor(text: str) -> tuple[int, bytes]:
    return len(text), hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest()


def _without_witness(event: dict[str, Any]) -> dict[str, Any]:
    if WITNESS_FIELD not in event:
        return event
    return {key: value for key, value in event.items() if key != WITNESS_FIELD}


class SessionStreamItemDelta:
    def __init__(self) -> None:
        self._turn: tuple[str, str] | None = None
        self._fingerprints: dict[tuple[str, str], bytes] = {}
        # identity -> (length, digest) of the text last delivered on THIS
        # connection (via a full row or via cumulative appends). Appends are
        # cut at this cursor and only when the new text hash-verifies as a
        # strict extension of it.
        self._text_cursors: dict[tuple[str, str], tuple[int, bytes]] = {}

    def compact(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") != "assistant_delta":
            # A detail/bootstrap snapshot can replace the client's active layer.
            self._reset()
            return _without_witness(event)
        witness = event.get(WITNESS_FIELD)
        if isinstance(witness, AssistantDeltaFrameWitness):
            return self._compact_with_witness(event, witness)
        return _without_witness(self._compact_recompute(event))

    def _compact_recompute(self, event: dict[str, Any]) -> dict[str, Any]:
        turn = (str(event.get("sessionId") or ""), str(event.get("turnId") or ""))
        items = event.get("turnItems")
        if not all(turn) or not isinstance(items, list):
            self._reset()
            return event
        fingerprints: dict[tuple[str, str], bytes] = {}
        changed: list[dict[str, Any]] = []
        appends: list[dict[str, Any]] = []
        text_cursors: dict[tuple[str, str], tuple[int, bytes]] = {}
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("version") != 3
                or not item.get("id")
                or not item.get("itemId")
                or (str(item.get("sessionId") or ""), str(item.get("turnId") or "")) != turn
            ):
                self._reset()
                return event
            # Match the frontend's canonicalItemIdentity, including call identity.
            identity = ("call", str(item.get("callId") or "")) if item.get("type") == "tool_call" else ("item", str(item["itemId"]))
            if not identity[1] or identity in fingerprints:
                self._reset()
                return event
            # Revisions alone do not cover same-revision text/metadata updates.
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            fingerprint = hashlib.blake2b(encoded, digest_size=16).digest()
            fingerprints[identity] = fingerprint
            text = _item_text(item) if item.get("type") in TEXT_APPEND_ITEM_TYPES else None
            if text is not None:
                text_cursors[identity] = _text_cursor(text)
            if self._fingerprints.get(identity) == fingerprint:
                continue
            append_entry = self._append_entry_for(item, identity, text)
            if append_entry is not None:
                appends.append(append_entry)
            else:
                changed.append(item)
        full = (
            self._turn != turn
            or bool(event.get("done"))
            or not self._fingerprints.keys() <= fingerprints.keys()
        )
        self._turn = turn
        self._fingerprints = fingerprints
        self._text_cursors = text_cursors
        if full:
            # Terminal / turn-switch / item-set-shrink frames stay verbatim full
            # snapshots; the cursors committed above already match their rows.
            return event
        compacted: dict[str, Any] = {**event, "turnItems": changed}
        if appends:
            compacted["turnItemAppends"] = appends
            compacted["streamEncoding"] = STREAM_ENCODING_APPEND
        return compacted

    def _compact_with_witness(self, event: dict[str, Any], witness: AssistantDeltaFrameWitness) -> dict[str, Any]:
        turn = (str(event.get("sessionId") or ""), str(event.get("turnId") or ""))
        items = event.get("turnItems")
        if not all(turn) or not isinstance(items, list):
            self._reset()
            return _without_witness(event)
        fingerprints: dict[tuple[str, str], bytes] = {}
        changed: list[dict[str, Any]] = []
        appends: list[dict[str, Any]] = []
        text_cursors: dict[tuple[str, str], tuple[int, bytes]] = {}
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("version") != 3
                or not item.get("id")
                or not item.get("itemId")
                or (str(item.get("sessionId") or ""), str(item.get("turnId") or "")) != turn
            ):
                self._reset()
                return _without_witness(event)
            identity = ("call", str(item.get("callId") or "")) if item.get("type") == "tool_call" else ("item", str(item["itemId"]))
            if not identity[1] or identity in fingerprints:
                self._reset()
                return _without_witness(event)
            # The witness fingerprint was maintained incrementally at publish
            # time; no per-frame re-serialization of the row happens here.
            fingerprint = witness.fingerprints.get(identity)
            if fingerprint is None:
                # Inconsistent witness: fall open through the full recompute.
                self._reset()
                return _without_witness(self._compact_recompute(event))
            fingerprints[identity] = fingerprint
            cursor = witness.text_cursors.get(identity)
            if cursor is not None:
                text_cursors[identity] = cursor
            if self._fingerprints.get(identity) == fingerprint:
                continue
            append_entry = self._witness_append_entry(item, identity, witness)
            if append_entry is not None:
                appends.append(append_entry)
            else:
                changed.append(item)
        full = (
            self._turn != turn
            or bool(event.get("done"))
            or not self._fingerprints.keys() <= fingerprints.keys()
        )
        self._turn = turn
        self._fingerprints = fingerprints
        self._text_cursors = text_cursors
        stripped = _without_witness(event)
        if full:
            return stripped
        compacted: dict[str, Any] = {**stripped, "turnItems": changed}
        if appends:
            compacted["turnItemAppends"] = appends
            compacted["streamEncoding"] = STREAM_ENCODING_APPEND
        return compacted

    def _reset(self) -> None:
        self._turn = None
        self._fingerprints.clear()
        self._text_cursors.clear()

    def _append_entry_for(
        self,
        item: dict[str, Any],
        identity: tuple[str, str],
        text: str | None,
    ) -> dict[str, Any] | None:
        """Return an append entry when the item's text strictly extends the
        text last delivered on this connection; ``None`` sends the full row."""

        if text is None:
            return None
        cursor = self._text_cursors.get(identity)
        if cursor is None:
            return None
        previous_length, previous_digest = cursor
        if len(text) <= previous_length:
            # Rewrite, truncation, or equal-length mutation: never guess.
            return None
        prefix = text[:previous_length].encode("utf-8")
        if hashlib.blake2b(prefix, digest_size=16).digest() != previous_digest:
            # The delivered text is not a prefix of the new text: appending
            # would splice a rewritten body onto a stale client row.
            return None
        appended_text = text[previous_length:]
        if not appended_text:
            return None
        return {
            "kind": APPEND_ENTRY_KIND,
            "itemId": str(item["itemId"]),
            "itemType": str(item.get("type") or ""),
            "baseLength": previous_length,
            "appendedLength": len(appended_text),
            "appendedText": appended_text,
        }

    def _witness_append_entry(
        self,
        item: dict[str, Any],
        identity: tuple[str, str],
        witness: AssistantDeltaFrameWitness,
    ) -> dict[str, Any] | None:
        """Witness-backed variant of :meth:`_append_entry_for`.

        Prefix verification consults the projector's digest chain instead of
        re-hashing the delivered prefix, so the per-frame cost is O(delta).
        A cursor missing from the chain (pruned history, rewrite baseline)
        falls back to the full row exactly like an unverifiable prefix.
        """

        text = _item_text(item) if item.get("type") in TEXT_APPEND_ITEM_TYPES else None
        if text is None:
            return None
        cursor = self._text_cursors.get(identity)
        if cursor is None:
            return None
        previous_length, previous_digest = cursor
        if len(text) <= previous_length:
            return None
        history = witness.prefix_history.get(identity) or {}
        if history.get(previous_length) != previous_digest:
            return None
        appended_text = text[previous_length:]
        if not appended_text:
            return None
        return {
            "kind": APPEND_ENTRY_KIND,
            "itemId": str(item["itemId"]),
            "itemType": str(item.get("type") or ""),
            "baseLength": previous_length,
            "appendedLength": len(appended_text),
            "appendedText": appended_text,
        }
