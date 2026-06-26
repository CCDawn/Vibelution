from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.runtime_manager.constants import PROJECT_ROOT


DESKTOP_SESSION_DB_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "desktop_sessions.sqlite3"
DESKTOP_SESSION_HEARTBEAT_LEASE_SECONDS = 45
WINDOW_ROLES = {"launcher", "workbench"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def _connect() -> sqlite3.Connection:
    DESKTOP_SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DESKTOP_SESSION_DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS desktop_sessions (
          desktop_session_id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          status TEXT NOT NULL,
          revision INTEGER NOT NULL,
          workspace_root TEXT NOT NULL,
          capabilities_json TEXT NOT NULL,
          windows_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_heartbeat_at TEXT NOT NULL,
          closed_at TEXT NOT NULL DEFAULT ''
        );
        """
    )


def register_desktop_session(payload: dict[str, Any]) -> dict[str, Any]:
    desktop_session_id = _safe_text(payload.get("desktopSessionId"), max_length=160)
    if not desktop_session_id:
        raise ValueError("desktopSessionId is required")
    provider = _safe_text(payload.get("provider"), max_length=80) or "electron"
    workspace_root = _safe_text(payload.get("workspaceRoot"), max_length=1000)
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else []
    safe_capabilities = [_safe_text(item, max_length=160) for item in capabilities if _safe_text(item, max_length=160)]
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (desktop_session_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO desktop_sessions (
                  desktop_session_id, provider, status, revision, workspace_root,
                  capabilities_json, windows_json, created_at, updated_at, last_heartbeat_at
                ) VALUES (?, ?, 'active', 1, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    desktop_session_id,
                    provider,
                    workspace_root,
                    json.dumps(safe_capabilities, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE desktop_sessions
                SET provider = ?,
                    status = 'active',
                    revision = revision + 1,
                    workspace_root = ?,
                    capabilities_json = ?,
                    updated_at = ?,
                    last_heartbeat_at = ?,
                    closed_at = ''
                WHERE desktop_session_id = ?
                """,
                (
                    provider,
                    workspace_root,
                    json.dumps(safe_capabilities, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                    desktop_session_id,
                ),
            )
        row = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (desktop_session_id,),
        ).fetchone()
        conn.execute("COMMIT")
    return _public_session(row)


def update_desktop_session_window(desktop_session_id: str, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    normalized_role = _safe_text(role, max_length=80)
    if normalized_role not in WINDOW_ROLES:
        raise ValueError(f"unsupported desktop session window role: {normalized_role}")
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_session_row(conn, normalized_id, now)
        windows = json.loads(str(row["windows_json"] or "{}"))
        windows[normalized_role] = _window_payload(normalized_role, payload)
        conn.execute(
            """
            UPDATE desktop_sessions
            SET status = 'active',
                revision = revision + 1,
                windows_json = ?,
                updated_at = ?,
                last_heartbeat_at = ?
            WHERE desktop_session_id = ?
            """,
            (json.dumps(windows, ensure_ascii=False, sort_keys=True), now, now, normalized_id),
        )
        updated = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (normalized_id,),
        ).fetchone()
        conn.execute("COMMIT")
    return _public_session(updated)


def heartbeat_desktop_session(desktop_session_id: str) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_session_row(conn, normalized_id, now)
        conn.execute(
            """
            UPDATE desktop_sessions
            SET status = 'active',
                revision = revision + 1,
                updated_at = ?,
                last_heartbeat_at = ?
            WHERE desktop_session_id = ?
            """,
            (now, now, normalized_id),
        )
        updated = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (normalized_id,),
        ).fetchone()
        conn.execute("COMMIT")
    return _public_session(updated)


def close_desktop_session(desktop_session_id: str) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_session_row(conn, normalized_id, now)
        conn.execute(
            """
            UPDATE desktop_sessions
            SET status = 'closed',
                revision = revision + 1,
                updated_at = ?,
                closed_at = ?
            WHERE desktop_session_id = ?
            """,
            (now, now, normalized_id),
        )
        updated = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (normalized_id,),
        ).fetchone()
        conn.execute("COMMIT")
    return _public_session(updated)


def latest_active_desktop_window(role: str) -> dict[str, Any]:
    normalized_role = _safe_text(role, max_length=80)
    if normalized_role not in WINDOW_ROLES:
        raise ValueError(f"unsupported desktop session window role: {normalized_role}")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM desktop_sessions
            WHERE status = 'active'
            ORDER BY last_heartbeat_at DESC, updated_at DESC
            LIMIT 20
            """
        ).fetchall()
    for row in rows:
        if not _lease_active(row):
            continue
        windows = json.loads(row["windows_json"] or "{}")
        window = windows.get(normalized_role)
        if not isinstance(window, dict):
            continue
        return {
            **window,
            "desktopSessionId": row["desktop_session_id"],
            "desktopSessionRevision": int(row["revision"] or 0),
            "desktopSessionLeaseExpiresAt": _lease_expires_at(str(row["last_heartbeat_at"] or "")).isoformat(),
        }
    return {}


def _ensure_session_row(conn: sqlite3.Connection, desktop_session_id: str, now: str) -> sqlite3.Row:
    if not desktop_session_id:
        raise ValueError("desktopSessionId is required")
    row = conn.execute(
        "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
        (desktop_session_id,),
    ).fetchone()
    if row is not None:
        return row
    conn.execute(
        """
        INSERT INTO desktop_sessions (
          desktop_session_id, provider, status, revision, workspace_root,
          capabilities_json, windows_json, created_at, updated_at, last_heartbeat_at
        ) VALUES (?, 'electron', 'active', 1, '', '[]', '{}', ?, ?, ?)
        """,
        (desktop_session_id, now, now, now),
    )
    return conn.execute(
        "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
        (desktop_session_id,),
    ).fetchone()


def _window_payload(role: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": role,
        "provider": _safe_text(payload.get("provider"), max_length=80) or "electron",
        "open": bool(payload.get("open", False)),
        "focused": bool(payload.get("focused", False)),
        "windowId": _safe_int(payload.get("windowId")),
        "rendererProcessId": _safe_int(payload.get("rendererProcessId")),
        "url": _safe_text(payload.get("url"), max_length=1000),
    }


def _public_session(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "desktopSessionId": row["desktop_session_id"],
        "provider": row["provider"],
        "status": row["status"],
        "revision": int(row["revision"] or 0),
        "workspaceRoot": row["workspace_root"],
        "capabilities": json.loads(row["capabilities_json"] or "[]"),
        "windows": json.loads(row["windows_json"] or "{}"),
        "updatedAt": row["updated_at"],
        "lastHeartbeatAt": row["last_heartbeat_at"],
        "leaseExpiresAt": _lease_expires_at(str(row["last_heartbeat_at"] or "")).isoformat(),
        "closedAt": row["closed_at"] or "",
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _lease_active(row: sqlite3.Row) -> bool:
    if str(row["status"] or "") != "active":
        return False
    return _lease_expires_at(str(row["last_heartbeat_at"] or "")) > datetime.now(timezone.utc)


def _lease_expires_at(last_heartbeat_at: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(last_heartbeat_at or "").replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) + timedelta(seconds=DESKTOP_SESSION_HEARTBEAT_LEASE_SECONDS)
