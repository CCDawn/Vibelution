"""Plugin-local FIFO mailbox for virtual-human conversation commands.

The mailbox is an Agent-scoped scheduling ledger, not a transcript.  It may
hold a bounded pending command until the native Session turn can accept it;
once dispatched, the existing Session journal and SSE pipeline remain the
only conversation authority.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

MAILBOX_SCHEMA_VERSION = 1
_SOURCE_KINDS = {"user", "proactive", "followup"}
_SOURCE_PRIORITY = {"user": 0, "proactive": 1, "followup": 2}
_ENTRY_STATES = {
    "queued",
    "dispatching",
    "awaiting_native_admission",
    "completed",
    "cancelled",
}
_COMMAND_KEYS = {
    "content",
    "clientSubmissionId",
    "contentUtf8Base64",
    "attachmentIds",
    "references",
    "mentalModelEnabled",
    "runtimeStatusEnabled",
    "turnStatusTail",
    "proactiveAttempt",
    "idempotencyKey",
}


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def _parse(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_mailbox(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a validated copy while preserving monotonic session cursors."""

    if payload is None:
        return {
            "schemaVersion": MAILBOX_SCHEMA_VERSION,
            "nextSequenceBySession": {},
            "entries": [],
        }
    if int(payload.get("schemaVersion") or 0) != MAILBOX_SCHEMA_VERSION:
        raise ValueError("Unsupported virtual-human mailbox schema version.")
    raw_entries = payload.get("entries")
    raw_cursors = payload.get("nextSequenceBySession")
    if not isinstance(raw_entries, list) or not isinstance(raw_cursors, Mapping):
        raise TypeError("Virtual-human mailbox is malformed.")

    entries: list[dict[str, Any]] = []
    max_sequences: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_session_sequences: set[tuple[str, int]] = set()
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise TypeError("Virtual-human mailbox entry must be an object.")
        entry = deepcopy(dict(raw))
        entry_id = str(entry.get("entryId") or "").strip()
        session_id = str(entry.get("sessionId") or "").strip()
        source_kind = str(entry.get("sourceKind") or "").strip().lower()
        state = str(entry.get("state") or "").strip().lower()
        sequence = int(entry.get("arrivalSequence") or 0)
        generation = int(entry.get("generation") or 0)
        command = entry.get("command")
        command_fingerprint = str(entry.get("commandFingerprint") or "").strip()
        if not command_fingerprint and isinstance(command, Mapping) and command:
            command_fingerprint = _command_fingerprint(command)
        if (
            not entry_id
            or not session_id
            or entry_id in seen_ids
            or source_kind not in _SOURCE_KINDS
            or state not in _ENTRY_STATES
            or sequence < 1
            or generation < 0
            or not isinstance(command, Mapping)
            or not command_fingerprint
        ):
            raise ValueError("Virtual-human mailbox entry is malformed.")
        session_sequence = (session_id, sequence)
        if session_sequence in seen_session_sequences:
            raise ValueError("Virtual-human mailbox sequence is duplicated.")
        if state not in {"completed", "cancelled"}:
            _validate_command(command)
        entry.update(
            {
                "entryId": entry_id,
                "sessionId": session_id,
                "sourceKind": source_kind,
                "state": state,
                "arrivalSequence": sequence,
                "generation": generation,
                "command": deepcopy(dict(command)),
                "commandFingerprint": command_fingerprint,
            }
        )
        entries.append(entry)
        seen_ids.add(entry_id)
        seen_session_sequences.add(session_sequence)
        max_sequences[session_id] = max(max_sequences.get(session_id, 0), sequence)

    cursors: dict[str, int] = {}
    for raw_session_id, raw_value in raw_cursors.items():
        session_id = str(raw_session_id or "").strip()
        if not session_id:
            raise ValueError("Virtual-human mailbox cursor has no Session id.")
        cursors[session_id] = max(1, int(raw_value or 1))
    for session_id, max_sequence in max_sequences.items():
        cursors[session_id] = max(cursors.get(session_id, 1), max_sequence + 1)
    entries.sort(key=lambda item: (str(item["sessionId"]), int(item["arrivalSequence"])))
    return {
        "schemaVersion": MAILBOX_SCHEMA_VERSION,
        "nextSequenceBySession": cursors,
        "entries": entries,
    }


def enqueue_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    session_id: str,
    source_kind: str,
    command: Mapping[str, Any],
    generation: int,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_source = str(source_kind or "").strip().lower()
    normalized_generation = int(generation)
    if not normalized_entry_id or not normalized_session_id:
        raise ValueError("Virtual-human mailbox enqueue requires entry and Session ids.")
    if normalized_source not in _SOURCE_KINDS:
        raise ValueError("Unsupported virtual-human mailbox source kind.")
    if normalized_generation < 0:
        raise ValueError("Virtual-human mailbox generation must be non-negative.")
    _validate_command(command)
    command_fingerprint = _command_fingerprint(command)
    for existing in state["entries"]:
        if str(existing.get("entryId") or "") != normalized_entry_id:
            continue
        if (
            str(existing.get("sessionId") or "") != normalized_session_id
            or str(existing.get("sourceKind") or "") != normalized_source
            or str(existing.get("commandFingerprint") or "")
            != command_fingerprint
        ):
            raise ValueError(
                "Virtual-human mailbox entry id conflicts with another command."
            )
        return state, {**deepcopy(existing), "enqueueOutcome": "reused"}

    cursors = dict(state["nextSequenceBySession"])
    sequence = max(1, int(cursors.get(normalized_session_id) or 1))
    cursors[normalized_session_id] = sequence + 1
    entry = {
        "entryId": normalized_entry_id,
        "sessionId": normalized_session_id,
        "arrivalSequence": sequence,
        "sourceKind": normalized_source,
        "state": "queued",
        "generation": normalized_generation,
        "command": deepcopy(dict(command)),
        "commandFingerprint": command_fingerprint,
        "leaseToken": "",
        "leaseOwner": "",
        "leaseExpiresAt": "",
        "leaseAttempt": 0,
        "turnId": "",
        "cancelReason": "",
        "createdAt": _iso(now),
        "updatedAt": _iso(now),
    }
    state["nextSequenceBySession"] = cursors
    state["entries"].append(entry)
    state["entries"].sort(
        key=lambda item: (str(item["sessionId"]), int(item["arrivalSequence"]))
    )
    return state, {**deepcopy(entry), "enqueueOutcome": "enqueued"}


def claim_next_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    session_id: str,
    lease_owner: str,
    now: datetime,
    lease_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    state = normalize_mailbox(mailbox)
    normalized_session_id = str(session_id or "").strip()
    normalized_owner = str(lease_owner or "").strip()
    bounded_lease_seconds = int(lease_seconds)
    if not normalized_session_id or not normalized_owner:
        raise ValueError("Virtual-human mailbox claim requires Session and owner ids.")
    if bounded_lease_seconds < 1:
        raise ValueError("Virtual-human mailbox lease must be positive.")
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    if any(
        str(entry.get("sessionId") or "") == normalized_session_id
        and str(entry.get("state") or "") == "awaiting_native_admission"
        for entry in state["entries"]
    ):
        return state, None

    for entry in state["entries"]:
        if str(entry.get("sessionId") or "") != normalized_session_id:
            continue
        if str(entry.get("state") or "") != "dispatching":
            continue
        expires_at = _parse(entry.get("leaseExpiresAt"))
        if expires_at is not None and expires_at > current:
            return state, None
        entry.update(
            {
                "state": "queued",
                "leaseToken": "",
                "leaseOwner": "",
                "leaseExpiresAt": "",
                "updatedAt": _iso(current),
            }
        )

    candidates = [
        entry
        for entry in state["entries"]
        if str(entry.get("sessionId") or "") == normalized_session_id
        and str(entry.get("state") or "") == "queued"
    ]
    candidate = min(
        candidates,
        key=lambda item: (
            _SOURCE_PRIORITY.get(str(item.get("sourceKind") or ""), 99),
            int(item.get("arrivalSequence") or 0),
        ),
        default=None,
    )
    if candidate is None:
        return state, None
    candidate.update(
        {
            "state": "dispatching",
            "leaseToken": uuid.uuid4().hex,
            "leaseOwner": normalized_owner,
            "leaseExpiresAt": _iso(current + timedelta(seconds=bounded_lease_seconds)),
            "leaseAttempt": int(candidate.get("leaseAttempt") or 0) + 1,
            "updatedAt": _iso(current),
        }
    )
    return state, deepcopy(candidate)


def complete_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    lease_token: str,
    turn_id: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    entry = next(
        (item for item in state["entries"] if str(item.get("entryId") or "") == normalized_entry_id),
        None,
    )
    if entry is None:
        raise ValueError("Virtual-human mailbox entry does not exist.")
    if str(entry.get("state") or "") == "completed":
        if normalized_turn_id and str(entry.get("turnId") or "") != normalized_turn_id:
            raise ValueError("Completed mailbox entry belongs to another turn.")
        return state, deepcopy(entry)
    if (
        str(entry.get("state") or "") != "dispatching"
        or str(entry.get("leaseToken") or "") != str(lease_token or "").strip()
    ):
        raise ValueError("Mailbox completion requires the matching active lease.")
    if not normalized_turn_id:
        raise ValueError("Mailbox completion requires a native Session turn id.")
    entry.update(
        {
            "state": "completed",
            "turnId": normalized_turn_id,
            "command": {},
            "leaseToken": "",
            "leaseOwner": "",
            "leaseExpiresAt": "",
            "completedAt": _iso(now),
            "updatedAt": _iso(now),
        }
    )
    return state, deepcopy(entry)


def await_mailbox_entry_native_admission(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    lease_token: str,
    turn_id: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep FIFO closed while an accepted proactive Turn waits in native scheduling."""

    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    entry = next(
        (
            item
            for item in state["entries"]
            if str(item.get("entryId") or "") == normalized_entry_id
        ),
        None,
    )
    if entry is None:
        raise ValueError("Virtual-human mailbox entry does not exist.")
    if (
        str(entry.get("state") or "") != "dispatching"
        or str(entry.get("leaseToken") or "") != str(lease_token or "").strip()
    ):
        raise ValueError("Mailbox admission wait requires the matching active lease.")
    if not normalized_turn_id:
        raise ValueError("Mailbox admission wait requires a native Session turn id.")
    entry.update(
        {
            "state": "awaiting_native_admission",
            "turnId": normalized_turn_id,
            "leaseToken": "",
            "leaseOwner": "",
            "leaseExpiresAt": "",
            "nativeAcceptedAt": _iso(now),
            "updatedAt": _iso(now),
        }
    )
    return state, deepcopy(entry)


def complete_awaiting_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    turn_id: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Close an admission wait only after the native Turn-start receipt exists."""

    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    entry = next(
        (
            item
            for item in state["entries"]
            if str(item.get("entryId") or "") == normalized_entry_id
        ),
        None,
    )
    if entry is None:
        raise ValueError("Virtual-human mailbox entry does not exist.")
    if str(entry.get("state") or "") == "completed":
        if normalized_turn_id and str(entry.get("turnId") or "") != normalized_turn_id:
            raise ValueError("Completed mailbox entry belongs to another turn.")
        return state, deepcopy(entry)
    if str(entry.get("state") or "") != "awaiting_native_admission":
        raise ValueError("Mailbox entry is not waiting for native admission.")
    if not normalized_turn_id or str(entry.get("turnId") or "") != normalized_turn_id:
        raise ValueError("Native admission receipt belongs to another turn.")
    entry.update(
        {
            "state": "completed",
            "command": {},
            "completedAt": _iso(now),
            "updatedAt": _iso(now),
        }
    )
    return state, deepcopy(entry)


def release_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    lease_token: str,
    reason: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one unaccepted command to its original FIFO position."""

    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    entry = next(
        (item for item in state["entries"] if str(item.get("entryId") or "") == normalized_entry_id),
        None,
    )
    if entry is None:
        raise ValueError("Virtual-human mailbox entry does not exist.")
    if (
        str(entry.get("state") or "") != "dispatching"
        or str(entry.get("leaseToken") or "") != str(lease_token or "").strip()
    ):
        raise ValueError("Mailbox release requires the matching active lease.")
    entry.update(
        {
            "state": "queued",
            "leaseToken": "",
            "leaseOwner": "",
            "leaseExpiresAt": "",
            "lastReleaseReason": str(reason or "").strip()[:120],
            "updatedAt": _iso(now),
        }
    )
    return state, deepcopy(entry)


def cancel_mailbox_entry(
    mailbox: Mapping[str, Any] | None,
    *,
    entry_id: str,
    reason: str,
    now: datetime,
    lease_token: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cancel one unsent command without manufacturing a native turn."""

    state = normalize_mailbox(mailbox)
    normalized_entry_id = str(entry_id or "").strip()
    normalized_lease_token = str(lease_token or "").strip()
    entry = next(
        (item for item in state["entries"] if str(item.get("entryId") or "") == normalized_entry_id),
        None,
    )
    if entry is None:
        raise ValueError("Virtual-human mailbox entry does not exist.")
    if str(entry.get("state") or "") == "cancelled":
        return state, deepcopy(entry)
    if str(entry.get("state") or "") == "completed":
        raise ValueError("Completed mailbox entries cannot be cancelled.")
    if str(entry.get("state") or "") == "dispatching" and (
        not normalized_lease_token
        or str(entry.get("leaseToken") or "") != normalized_lease_token
    ):
        raise ValueError("Mailbox cancellation requires the matching active lease.")
    entry.update(
        {
            "state": "cancelled",
            "command": {},
            "cancelReason": str(reason or "").strip()[:120],
            "leaseToken": "",
            "leaseOwner": "",
            "leaseExpiresAt": "",
            "cancelledAt": _iso(now),
            "updatedAt": _iso(now),
        }
    )
    return state, deepcopy(entry)


def cancel_unsent_followups(
    mailbox: Mapping[str, Any] | None,
    *,
    session_id: str,
    before_generation: int,
    reason: str,
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    state = normalize_mailbox(mailbox)
    normalized_session_id = str(session_id or "").strip()
    normalized_generation = int(before_generation)
    normalized_reason = str(reason or "").strip()[:120]
    cancelled: list[str] = []
    for entry in state["entries"]:
        if (
            str(entry.get("sessionId") or "") != normalized_session_id
            or str(entry.get("sourceKind") or "") != "followup"
            or str(entry.get("state") or "")
            not in {"queued", "dispatching", "awaiting_native_admission"}
            or int(entry.get("generation") or 0) >= normalized_generation
        ):
            continue
        entry.update(
            {
                "state": "cancelled",
                "command": {},
                "cancelReason": normalized_reason,
                "leaseToken": "",
                "leaseOwner": "",
                "leaseExpiresAt": "",
                "cancelledAt": _iso(now),
                "updatedAt": _iso(now),
            }
        )
        cancelled.append(str(entry["entryId"]))
    return state, cancelled


def _validate_command(command: Mapping[str, Any]) -> None:
    if not isinstance(command, Mapping) or not command:
        raise ValueError("Virtual-human mailbox command must be a non-empty object.")
    unexpected = {str(key) for key in command} - _COMMAND_KEYS
    if unexpected:
        raise ValueError("Virtual-human mailbox command contains transcript or unsupported fields.")
    if "content" not in command and "proactiveAttempt" not in command:
        raise ValueError("Virtual-human mailbox command needs content or a proactive attempt.")


def _command_fingerprint(command: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            dict(command),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Virtual-human mailbox command must be JSON serializable.") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MAILBOX_SCHEMA_VERSION",
    "await_mailbox_entry_native_admission",
    "cancel_mailbox_entry",
    "cancel_unsent_followups",
    "claim_next_mailbox_entry",
    "complete_awaiting_mailbox_entry",
    "complete_mailbox_entry",
    "enqueue_mailbox_entry",
    "normalize_mailbox",
    "release_mailbox_entry",
]
