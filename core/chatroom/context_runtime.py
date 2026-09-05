"""Small runtime seams for chat-room structured context integration."""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

STRUCTURED_CONTEXT_ENV = "VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED"
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def chat_room_structured_context_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return the default-on room feature flag without reading app config."""

    source = os.environ if environ is None else environ
    raw = str(source.get(STRUCTURED_CONTEXT_ENV, "") or "").strip().lower()
    return raw not in _FALSE_VALUES


def last_chat_room_message_ref(room: Mapping[str, Any]) -> str:
    """Return the authoritative tail ref used by the Room Store CAS."""

    room_id = str(room.get("roomId") or room.get("id") or "").strip()
    for round_payload in reversed(list(room.get("rounds") or [])):
        if not isinstance(round_payload, Mapping):
            continue
        round_id = str(round_payload.get("roundId") or round_payload.get("id") or "").strip()
        for message in reversed(list(round_payload.get("messages") or [])):
            if not isinstance(message, Mapping):
                continue
            message_id = str(message.get("messageId") or message.get("id") or "").strip()
            if room_id and round_id and message_id:
                return f"{room_id}/{round_id}/{message_id}"
    return ""


def commit_chat_room_context_checkpoint(
    state: dict[str, Any],
    *,
    room_id: str,
    expected_last_message_ref: str,
    checkpoint: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Apply a precomputed checkpoint only when the room tail has not moved.

    The caller owns the existing Room Store lock and persists ``state`` after a
    successful result.  No retry or hidden overwrite occurs here.
    """

    normalized_room_id = str(room_id or "").strip()
    for room in list(state.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        if str(room.get("roomId") or room.get("id") or "").strip() != normalized_room_id:
            continue
        actual_ref = last_chat_room_message_ref(room)
        if actual_ref != str(expected_last_message_ref or "").strip():
            return {
                "committed": False,
                "reason": "room_advanced",
                "expectedLastMessageRef": str(expected_last_message_ref or "").strip(),
                "actualLastMessageRef": actual_ref,
            }
        if checkpoint is None:
            room.pop("contextCheckpoint", None)
        else:
            room["contextCheckpoint"] = copy.deepcopy(dict(checkpoint))
        return {
            "committed": True,
            "reason": "updated",
            "actualLastMessageRef": actual_ref,
        }
    return {"committed": False, "reason": "room_missing"}


def chat_room_message_to_public(message: Mapping[str, Any]) -> dict[str, Any]:
    """Remove the internal ordinary-room protocol from an API projection."""

    public = copy.deepcopy(dict(message))
    public.pop("contextPayload", None)
    return public


def chat_room_context_segment_tokens(
    messages: Sequence[Mapping[str, Any]],
    *,
    estimate_tokens: Callable[[Sequence[Any]], int],
) -> dict[str, int]:
    """Measure the four prompt segments without changing message content."""

    buckets: dict[str, list[Mapping[str, Any]]] = {
        "system": [],
        "checkpoint": [],
        "delta": [],
        "recentRaw": [],
    }
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "").strip().lower()
        metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
        kind = str(metadata.get("kind") or "").strip()
        if role == "system":
            buckets["system"].append(message)
        elif kind == "chat_room_context_checkpoint":
            buckets["checkpoint"].append(message)
        elif kind == "chat_room_context_delta":
            buckets["delta"].append(message)
        elif kind == "group_room_transcript":
            buckets["recentRaw"].append(message)
    stats = {
        key: max(0, int(estimate_tokens(value))) if value else 0
        for key, value in buckets.items()
    }
    stats["total"] = sum(stats.values())
    return stats


__all__ = [
    "STRUCTURED_CONTEXT_ENV",
    "chat_room_context_segment_tokens",
    "chat_room_message_to_public",
    "chat_room_structured_context_enabled",
    "commit_chat_room_context_checkpoint",
    "last_chat_room_message_ref",
]
