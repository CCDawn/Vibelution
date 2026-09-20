"""Connection-local compression of cumulative TurnItems at the SSE write edge.

Queues and recovery keep full snapshots. Only a consumer that has already sent
an identical item may omit it; reconnecting consumers always start from full.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class SessionStreamItemDelta:
    def __init__(self) -> None:
        self._turn: tuple[str, str] | None = None
        self._fingerprints: dict[tuple[str, str], bytes] = {}

    def compact(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") != "assistant_delta":
            # A detail/bootstrap snapshot can replace the client's active layer.
            self._turn = None
            self._fingerprints.clear()
            return event
        turn = (str(event.get("sessionId") or ""), str(event.get("turnId") or ""))
        items = event.get("turnItems")
        if not all(turn) or not isinstance(items, list):
            self._turn = None
            self._fingerprints.clear()
            return event
        fingerprints: dict[tuple[str, str], bytes] = {}
        changed = []
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("version") != 3
                or not item.get("id")
                or not item.get("itemId")
                or (str(item.get("sessionId") or ""), str(item.get("turnId") or "")) != turn
            ):
                self._turn = None
                self._fingerprints.clear()
                return event
            # Match the frontend's canonicalItemIdentity, including call identity.
            identity = ("call", str(item.get("callId") or "")) if item.get("type") == "tool_call" else ("item", str(item["itemId"]))
            if not identity[1] or identity in fingerprints:
                self._turn = None
                self._fingerprints.clear()
                return event
            # Revisions alone do not cover same-revision text/metadata updates.
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            fingerprint = hashlib.blake2b(encoded, digest_size=16).digest()
            fingerprints[identity] = fingerprint
            if self._fingerprints.get(identity) != fingerprint:
                changed.append(item)
        full = (
            self._turn != turn
            or bool(event.get("done"))
            or not self._fingerprints.keys() <= fingerprints.keys()
        )
        self._turn = turn
        self._fingerprints = fingerprints
        if full:
            return event
        return {**event, "turnItems": changed}
