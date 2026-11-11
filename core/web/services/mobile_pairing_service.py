"""One-shot pairing codes that let a phone claim this instance's control token.

The desktop mints a code, the phone posts it back and receives the control
token. Codes are single-use and short-lived on purpose: holding that token is
equivalent to full control of the workbench, so a leaked code must expire fast
and must never be redeemable twice.

Claims are rate limited independently of the session store. Without that, a
caller could brute force the 10-character alphabet (32^10 space) by trying
codes against the token-exempt endpoint.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

PAIRING_TTL_SECONDS = 300
PAIRING_CODE_LENGTH = 10
# Crockford-style alphabet: no I, L, O, U. These codes get read off a screen and
# typed into a phone by hand, so the ambiguous glyphs are dropped.
_PAIRING_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_MAX_CLAIM_FAILURES = 5
_CLAIM_FAILURE_WINDOW_SECONDS = 60.0

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}
_CLAIM_FAILURE_TIMES: list[float] = []


def _now() -> float:
    return time.time()


def _prune_expired_locked(now: float) -> None:
    for code in [key for key, session in _SESSIONS.items() if session["expiresAt"] <= now]:
        _SESSIONS.pop(code, None)


def _prune_failures_locked(now: float) -> None:
    cutoff = now - _CLAIM_FAILURE_WINDOW_SECONDS
    while _CLAIM_FAILURE_TIMES and _CLAIM_FAILURE_TIMES[0] <= cutoff:
        _CLAIM_FAILURE_TIMES.pop(0)


def normalize_pairing_code(raw_code: str) -> str:
    """Fold display formatting (dashes, spaces, lowercase) back into the raw code."""
    return "".join(character for character in str(raw_code or "").upper() if character.isalnum())


def format_pairing_code(code: str) -> str:
    normalized = normalize_pairing_code(code)
    if len(normalized) != PAIRING_CODE_LENGTH:
        return normalized
    return f"{normalized[:5]}-{normalized[5:]}"


def create_pairing_code(*, host: str, port: int) -> dict[str, Any]:
    """Mint a fresh single-use code. Previous codes stay valid until they expire."""
    now = _now()
    with _LOCK:
        _prune_expired_locked(now)
        code = "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
        session = {
            "code": code,
            "host": str(host or ""),
            "port": int(port),
            "createdAt": now,
            "expiresAt": now + PAIRING_TTL_SECONDS,
        }
        _SESSIONS[code] = session
        return dict(session)


def claim_pairing_code(raw_code: str) -> dict[str, Any] | None:
    """Redeem a code once. Returns None for unknown, expired, or rate-limited claims.

    Deliberately does not distinguish those cases to the caller: the difference
    would tell an attacker whether a code ever existed.
    """
    normalized = normalize_pairing_code(raw_code)
    now = _now()
    with _LOCK:
        _prune_expired_locked(now)
        _prune_failures_locked(now)
        if len(_CLAIM_FAILURE_TIMES) >= _MAX_CLAIM_FAILURES:
            return None
        session = _SESSIONS.get(normalized)
        if session is None or session["expiresAt"] <= now:
            _CLAIM_FAILURE_TIMES.append(now)
            return None
        _SESSIONS.pop(normalized, None)
        return dict(session)


def reset_pairing_state() -> None:
    """Test hook: clear codes and failure history."""
    with _LOCK:
        _SESSIONS.clear()
        _CLAIM_FAILURE_TIMES.clear()
