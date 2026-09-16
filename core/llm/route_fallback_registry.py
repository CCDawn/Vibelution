# -*- coding: utf-8 -*-
"""In-memory registry of explicit LLM route fallback switches, keyed per turn.

The turn LLM adapter records one entry when a declared fallback route actually
served a turn after the primary route's retryable retry budget was exhausted.
The web session projection reads the same entry to expose the optional
``routeFallback`` (``{from, to}``) field on the turn detail DTO, so the switch
is visible to the operator instead of being a silent reroute.

Nothing here is persisted or logged; entries are bounded and evicted
oldest-first. Reads with no recorded switch return ``None``.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

_MAX_ENTRIES = 256

_LOCK = threading.Lock()
_ENTRIES: "OrderedDict[tuple[str, str], Dict[str, str]]" = OrderedDict()


def record_route_fallback(
    session_id: Any,
    turn_id: Any,
    *,
    from_profile_id: Any,
    to_profile_id: Any,
    reason: Any = "",
) -> Optional[Dict[str, str]]:
    """Record one explicit fallback switch for a turn; returns the DTO payload."""

    entry = normalize_route_fallback(
        {
            "from": from_profile_id,
            "to": to_profile_id,
            "reason": reason,
        }
    )
    if entry is None:
        return None
    key = (_text(session_id), _text(turn_id))
    with _LOCK:
        _ENTRIES.pop(key, None)
        _ENTRIES[key] = entry
        while len(_ENTRIES) > _MAX_ENTRIES:
            _ENTRIES.popitem(last=False)
    return route_fallback_payload(entry)


def get_route_fallback(session_id: Any, turn_id: Any = "") -> Optional[Dict[str, str]]:
    """Return the turn's switch payload (``{from, to}``), or ``None``.

    An exact (session, turn) match wins. With no turn id, the session's latest
    recorded switch is returned so a completed turn stays visible. With a turn
    id that has no recorded switch, ``None`` is returned: a turn that never
    switched must not be mislabelled with an older turn's entry. The returned
    mapping is the strict DTO shape; the switch reason lives on the
    ``llm_route_fallback_switched`` scene event instead.
    """

    session_key = _text(session_id)
    turn_key = _text(turn_id)
    with _LOCK:
        if turn_key:
            entry = _ENTRIES.get((session_key, turn_key))
            return route_fallback_payload(entry) if entry is not None else None
        for key in reversed(_ENTRIES):
            if key[0] == session_key:
                return route_fallback_payload(_ENTRIES[key])
    return None


def route_fallback_payload(entry: Any = None) -> Optional[Dict[str, str]]:
    """Project a stored entry into the strict ``{from, to}`` DTO shape."""

    source = entry if isinstance(entry, dict) else {}
    from_id = _text(source.get("from"))
    to_id = _text(source.get("to"))
    if not from_id or not to_id:
        return None
    return {"from": from_id, "to": to_id}


def normalize_route_fallback(value: Any) -> Optional[Dict[str, str]]:
    """Coerce arbitrary mapping input into a stored entry, or ``None``."""

    if not isinstance(value, dict):
        return None
    from_id = _text(value.get("from") or value.get("from_profile_id") or value.get("fromProfileId"))
    to_id = _text(value.get("to") or value.get("to_profile_id") or value.get("toProfileId"))
    if not from_id or not to_id or from_id == to_id:
        return None
    return {
        "from": from_id,
        "to": to_id,
        "reason": _text(value.get("reason") or value.get("errorCategory") or ""),
    }


def clear_route_fallbacks() -> None:
    """Drop every recorded switch (test isolation helper)."""

    with _LOCK:
        _ENTRIES.clear()


def _text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    return str(value or "").strip()


__all__ = [
    "clear_route_fallbacks",
    "get_route_fallback",
    "normalize_route_fallback",
    "record_route_fallback",
    "route_fallback_payload",
]
