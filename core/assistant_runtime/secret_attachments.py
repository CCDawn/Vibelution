"""In-process staging for personal-assistant privacy attachments.

Users hand the personal assistant secrets (API keys, tokens, passwords) as
chat attachments. The plaintext value never enters the conversation text or
the model context: the upload path stages the value in process memory only
and issues a one-shot ``sec_`` reference token; the model context receives a
presence marker instead, and tool execution later trades the token back for
the value (pop-on-read). Entries expire lazily after a fixed TTL and every
lookup also sweeps other expired entries. The store is process memory only:
nothing here touches disk, logs, or journals a value, and only metadata-free
helpers expose kind/label to the submit and tool layers.
"""

from __future__ import annotations

import secrets
import threading
import time

SECRET_KINDS = ("api_key", "token", "password", "secret")
SECRET_ATTACHMENT_TTL_SECONDS = 600
SECRET_ATTACHMENT_ID_PREFIX = "sec_"
# Bound the staged payload and its optional display label; real secrets are
# tiny and an unbounded dict would let one request pin process memory.
SECRET_MAX_VALUE_CHARS = 8192
SECRET_MAX_LABEL_CHARS = 120

_STORE_LOCK = threading.Lock()
# token -> (value, kind, created_monotonic, label)
_STORE: dict[str, tuple[str, str, float, str]] = {}


def _normalized_token(token: str) -> str:
    return str(token or "").strip()


def _normalize_label(label: str) -> str:
    # Label is display-only text (bubble name); bound it and drop control
    # characters so it cannot smuggle markup into metadata consumers.
    cleaned = "".join(char for char in str(label or "").strip() if ord(char) >= 32)
    if len(cleaned) > SECRET_MAX_LABEL_CHARS:
        cleaned = cleaned[:SECRET_MAX_LABEL_CHARS]
    return cleaned


def _purge_expired_locked(now: float | None = None) -> int:
    """Sweep expired entries; caller must hold _STORE_LOCK."""
    moment = time.monotonic() if now is None else now
    expired = [
        token
        for token, record in _STORE.items()
        if moment - record[2] >= SECRET_ATTACHMENT_TTL_SECONDS
    ]
    for token in expired:
        _STORE.pop(token, None)
    return len(expired)


def issue_secret_attachment(value: str, kind: str, *, label: str = "") -> str:
    """Stage one privacy value and return its one-shot ``sec_`` reference id.

    ``kind`` must be one of SECRET_KINDS; ``label`` is optional display-only
    text echoed back as attachment metadata. The plaintext is stored in
    process memory only and never logged.
    """
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind not in SECRET_KINDS:
        raise ValueError("unknown secret kind")
    if not isinstance(value, str) or not value or not value.strip():
        raise ValueError("secret value must be non-empty text")
    if len(value) > SECRET_MAX_VALUE_CHARS:
        raise ValueError("secret value is too large")
    token = f"{SECRET_ATTACHMENT_ID_PREFIX}{secrets.token_urlsafe(24)}"
    record = (value, normalized_kind, time.monotonic(), _normalize_label(label))
    with _STORE_LOCK:
        _purge_expired_locked(record[2])
        _STORE[token] = record
    return token


def resolve_secret_attachment(token: str) -> tuple[str, str] | None:
    """Pop-on-read: return ``(value, kind)`` once; expired or unknown -> None.

    This is the only accessor that hands out the value; tool execution is the
    intended consumer. A failed (expired) consume also drops the entry.
    """
    now = time.monotonic()
    with _STORE_LOCK:
        _purge_expired_locked(now)
        record = _STORE.pop(_normalized_token(token), None)
    if record is None or now - record[2] >= SECRET_ATTACHMENT_TTL_SECONDS:
        return None
    return record[0], record[1]


class SecretCredentialError(ValueError):
    """Credential-consumption failure carrying a stable message prefix.

    ``prefix`` is ``invalid_secret_reference`` (unknown, expired, or already
    consumed token) or ``kind_mismatch`` (live token whose stored kind differs
    from ``expected_kind``); consumers map failures to their own error codes
    by prefix instead of parsing secret-bearing messages.
    """

    def __init__(self, prefix: str) -> None:
        super().__init__(prefix)
        self.prefix = prefix


def consume_secret_credential(token: str, *, expected_kind: str | None = None) -> str:
    """One-shot consumer primitive: trade a ``sec_`` token for its value.

    Wraps resolve_secret_attachment, so pop-on-read, TTL and lazy-sweep
    semantics are unchanged. Unknown, expired, or already-consumed tokens
    raise SecretCredentialError with the ``invalid_secret_reference`` prefix
    (a failed consume never leaves the entry behind); when ``expected_kind``
    is given and the stored kind differs, the prefix is ``kind_mismatch`` —
    the pop has still consumed the entry.
    """
    resolved = resolve_secret_attachment(token)
    if resolved is None:
        raise SecretCredentialError("invalid_secret_reference")
    value, kind = resolved
    if expected_kind is not None and kind != expected_kind:
        raise SecretCredentialError("kind_mismatch")
    return value


def peek_secret_attachment(token: str) -> str | None:
    """Admission probe: return the secret kind while the entry is live.

    Never pops the entry and never returns the value; expired or unknown
    tokens return None.
    """
    now = time.monotonic()
    with _STORE_LOCK:
        _purge_expired_locked(now)
        record = _STORE.get(_normalized_token(token))
    if record is None or now - record[2] >= SECRET_ATTACHMENT_TTL_SECONDS:
        return None
    return record[1]


def secret_attachment_metadata(token: str) -> dict[str, str] | None:
    """Value-free journal metadata row for a live token; None when absent.

    Row shape is exactly ``{attachmentId, kind: "user_secret", label?}`` so
    persisted message metadata can never carry the plaintext.
    """
    normalized = _normalized_token(token)
    if peek_secret_attachment(normalized) is None:
        return None
    with _STORE_LOCK:
        record = _STORE.get(normalized)
    row = {"attachmentId": normalized, "kind": "user_secret"}
    if record and record[3]:
        row["label"] = record[3]
    return row


def purge_expired_secret_attachments() -> int:
    """Drop every expired entry and return how many were removed."""
    with _STORE_LOCK:
        return _purge_expired_locked()


def is_secret_attachment_id(value: str) -> bool:
    """True for submit ids shaped like privacy-attachment tokens."""
    candidate = _normalized_token(value)
    return bool(candidate) and candidate.startswith(SECRET_ATTACHMENT_ID_PREFIX)
