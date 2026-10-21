# -*- coding: utf-8 -*-
"""Identity-based de-duplication for journal replay projections.

Adjacent-content comparison misses duplicate journal rows whenever another event
lands between them (tool results, compression markers, recovery notices), which
is exactly how the same assistant output and the same user submission can reach
a projection twice. The journal already carries a stable item identity for
assistant output (``itemId``/``revision``/``sequence``); this module dedupes the
replayed projection on that identity first and only falls back to a content
digest for records that have none.

The journal stays append-only: nothing here rewrites, deletes or reorders
events, and no side-car state is persisted. Only the replayed projection is
deduped, and the first position of an identity is kept so a replay that sees an
older revision first still renders where the journal first produced it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

__all__ = ["dedupe_messages_by_identity", "message_identity_key"]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metadata(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _int_field(metadata: dict[str, Any], key: str) -> int:
    try:
        return int(metadata.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _content_digest(message: dict[str, Any]) -> str:
    payload = {
        "role": _text(message.get("role")),
        "content": _text(message.get("content")),
        "thought": _text(message.get("thought")),
        "toolCalls": message.get("toolCalls") or message.get("tool_calls") or [],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def message_identity_key(message: dict[str, Any]) -> tuple[str, ...]:
    """Stable identity for one replayed message.

    Canonical assistant items key on their journal item identity, so two
    genuinely distinct items that happen to share text stay separate. Records
    without an item identity (user rows, synthetic status rows) fall back to a
    content digest scoped to the turn and kind.
    """
    metadata = _metadata(message)
    turn_id = _text(metadata.get("turnId") or metadata.get("turn_id"))
    role = _text(message.get("role"))
    item_id = _text(metadata.get("itemId") or metadata.get("item_id"))
    if item_id:
        return ("item", turn_id, role, item_id)
    return ("content", turn_id, role, _text(metadata.get("kind")), _content_digest(message))


def dedupe_messages_by_identity(
    messages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one row per identity, preferring the highest revision.

    A later revision of the same item replaces the earlier one in place; a
    distinct item is never merged even when its text matches. The result keeps
    the order in which each identity first appeared.
    """
    order: list[tuple[str, ...]] = []
    winners: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            passthrough_key = ("passthrough", str(index))
            order.append(passthrough_key)
            winners[passthrough_key] = message  # type: ignore[assignment]
            continue
        key = message_identity_key(message)
        current = winners.get(key)
        if current is None:
            order.append(key)
            winners[key] = message
            continue
        metadata = _metadata(message)
        current_metadata = _metadata(current)
        incoming_rank = (_int_field(metadata, "revision"), _int_field(metadata, "sequence"))
        current_rank = (_int_field(current_metadata, "revision"), _int_field(current_metadata, "sequence"))
        if incoming_rank > current_rank:
            winners[key] = message
    return [winners[key] for key in order]
