"""Persistent read cursors backing the team and conversation unread projection.

The UI owns *when* something was read; this store only keeps the per-scope
read timestamp so unread survives restarts and browser switches. Unread itself
is derived in the client from the same session/room timestamps it already
renders, so there is exactly one message-timeline authority.

Scope kinds are intentionally closed: ``team`` (whole-team mark-read) and
``conversation`` (a direct session or a group room). Writes never move a
cursor backwards, which keeps concurrent "open conversation" and "mark team
read" requests monotonic.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from core.runtime_manager.constants import RUNTIME_ROOT

READ_CURSOR_DB_PATH = RUNTIME_ROOT / "chat" / "read_cursors.sqlite3"
READ_CURSOR_SCOPE_KINDS = frozenset({"team", "conversation"})
_MAX_SCOPE_ID_LENGTH = 200

_LOCK = threading.Lock()
_SCHEMA_READY = False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _connect() -> sqlite3.Connection:
    READ_CURSOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(READ_CURSOR_DB_PATH), timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS read_cursors (
            scope_kind TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            read_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_kind, scope_id)
        )
        """
    )


def _ensure_ready() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _LOCK:
        if _SCHEMA_READY:
            return
        connection = _connect()
        try:
            _ensure_schema(connection)
        finally:
            connection.close()
        _SCHEMA_READY = True


def _project(row: sqlite3.Row) -> dict[str, str]:
    return {
        "scopeKind": str(row["scope_kind"]),
        "scopeId": str(row["scope_id"]),
        "readAt": str(row["read_at"]),
    }


def list_read_cursors() -> list[dict[str, str]]:
    """Return every stored cursor ordered by scope for stable payloads."""

    _ensure_ready()
    connection = _connect()
    try:
        rows = connection.execute(
            "SELECT scope_kind, scope_id, read_at FROM read_cursors "
            "ORDER BY scope_kind ASC, scope_id ASC"
        ).fetchall()
    finally:
        connection.close()
    return [_project(row) for row in rows]


def _normalize_entry(entry: dict[str, Any], fallback_read_at: str) -> tuple[str, str, str]:
    scope_kind = str(entry.get("scopeKind") or entry.get("scope_kind") or "").strip()
    if scope_kind not in READ_CURSOR_SCOPE_KINDS:
        raise ValueError(f"unsupported scope kind: {scope_kind or '<empty>'}")
    scope_id = str(entry.get("scopeId") or entry.get("scope_id") or "").strip()
    if not scope_id or len(scope_id) > _MAX_SCOPE_ID_LENGTH:
        raise ValueError("scope id must be 1..200 characters")
    read_at = str(entry.get("readAt") or entry.get("read_at") or "").strip()
    if not read_at or len(read_at) > 64:
        read_at = fallback_read_at
    return scope_kind, scope_id, read_at


def mark_read(entries: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Upsert the given cursors and return the full cursor list.

    ``read_at`` is clamped to the stored value with SQLite ``max`` so a stale
    or concurrent write can never resurrect already-read content.
    """

    _ensure_ready()
    now = _now_iso()
    normalized: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        scope_kind, scope_id, read_at = _normalize_entry(entry, now)
        key = (scope_kind, scope_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((scope_kind, scope_id, read_at))
    if not normalized:
        return list_read_cursors()
    connection = _connect()
    try:
        with connection:
            for scope_kind, scope_id, read_at in normalized:
                connection.execute(
                    """
                    INSERT INTO read_cursors (scope_kind, scope_id, read_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(scope_kind, scope_id) DO UPDATE SET
                        read_at = max(read_cursors.read_at, excluded.read_at),
                        updated_at = excluded.updated_at
                    """,
                    (scope_kind, scope_id, read_at, now),
                )
    finally:
        connection.close()
    return list_read_cursors()
