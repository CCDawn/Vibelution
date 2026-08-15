from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.runtime_manager.constants import RUNTIME_ROOT


DESKTOP_SESSION_DB_PATH = RUNTIME_ROOT / "launcher" / "desktop_sessions.sqlite3"
DESKTOP_SESSION_HEARTBEAT_LEASE_SECONDS = 45
DESKTOP_SESSION_RETENTION_CLOSED_DAYS = 7
DESKTOP_SESSION_RETENTION_STALE_ACTIVE_DAYS = 30
DESKTOP_SESSION_PRUNE_INTERVAL_SECONDS = 3600
WINDOW_ROLES = {"launcher", "workbench"}

_INIT_CACHE_MAX_ENTRIES = 128
_schema_ready: OrderedDict[str, None] = OrderedDict()
_schema_guard = threading.Lock()
_last_prune_at = 0.0
_prune_guard = threading.Lock()


class DesktopSessionRevisionConflict(ValueError):
    def __init__(self, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"desktop session revision conflict: expected {expected_revision}, actual {actual_revision}"
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class DesktopSessionClosed(ValueError):
    def __init__(self, desktop_session_id: str, actual_revision: int) -> None:
        super().__init__(f"desktop session is closed: {desktop_session_id}")
        self.desktop_session_id = desktop_session_id
        self.actual_revision = actual_revision


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def _connect() -> sqlite3.Connection:
    DESKTOP_SESSION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DESKTOP_SESSION_DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
        conn.close()
        raise RuntimeError("desktop session store could not enable foreign_keys")
    _ensure_schema_once(conn)
    _maybe_prune_sessions(conn)
    return conn


def _ensure_schema_once(conn: sqlite3.Connection) -> None:
    """Run schema DDL in one startup transaction, once per process per path;
    runtime connections never execute DDL again."""
    key = str(DESKTOP_SESSION_DB_PATH)
    with _schema_guard:
        if key in _schema_ready:
            return
        # WAL is a persistent file mode; set it once under the guard so
        # concurrent first connects cannot race the exclusive lock switch.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            _init_schema(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        _schema_ready[key] = None
        while len(_schema_ready) > _INIT_CACHE_MAX_ENTRIES:
            _schema_ready.popitem(last=False)


def _init_schema(conn: sqlite3.Connection) -> None:
    _run_script(
        conn,
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
        CREATE INDEX IF NOT EXISTS idx_desktop_sessions_status_heartbeat
          ON desktop_sessions(status, last_heartbeat_at);
        CREATE INDEX IF NOT EXISTS idx_desktop_sessions_status_workspace_heartbeat
          ON desktop_sessions(status, replace(lower(workspace_root), '/', '\\'), last_heartbeat_at);
        """,
    )


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a DDL script statement-by-statement inside the caller's
    transaction (``executescript`` would implicitly commit it)."""
    for statement in script.split(";"):
        if statement.strip():
            conn.execute(statement)


def _maybe_prune_sessions(conn: sqlite3.Connection) -> None:
    global _last_prune_at
    with _prune_guard:
        if time.monotonic() - _last_prune_at < DESKTOP_SESSION_PRUNE_INTERVAL_SECONDS:
            return
    _prune_sessions(conn)
    with _prune_guard:
        _last_prune_at = time.monotonic()


def _prune_sessions(conn: sqlite3.Connection) -> None:
    """Bounded retention: drop closed rows after 7 days and stale active rows
    after 30 days. Rows inside the heartbeat lease are never removed."""
    now = datetime.now(timezone.utc)
    closed_cutoff = (now - timedelta(days=DESKTOP_SESSION_RETENTION_CLOSED_DAYS)).isoformat()
    stale_cutoff = (
        now - timedelta(days=DESKTOP_SESSION_RETENTION_STALE_ACTIVE_DAYS)
    ).isoformat()
    conn.execute(
        "DELETE FROM desktop_sessions WHERE status='closed' AND last_heartbeat_at < ?",
        (closed_cutoff,),
    )
    conn.execute(
        "DELETE FROM desktop_sessions WHERE status='active' AND last_heartbeat_at < ?",
        (stale_cutoff,),
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
            if str(existing["status"] or "") == "closed":
                conn.execute("ROLLBACK")
                raise DesktopSessionClosed(desktop_session_id, int(existing["revision"] or 0))
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
        _require_open_revision(row, payload)
        windows = json.loads(str(row["windows_json"] or "{}"))
        windows[normalized_role] = _window_payload(normalized_role, payload)
        conn.execute(
            """
            UPDATE desktop_sessions
            SET revision = revision + 1,
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


def heartbeat_desktop_session(desktop_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_session_row(conn, normalized_id, now)
        _require_open_revision(row, payload)
        conn.execute(
            """
            UPDATE desktop_sessions
            SET revision = revision + 1,
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


def close_desktop_session(desktop_session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_session_row(conn, normalized_id, now)
        actual_revision = int(row["revision"] or 0)
        expected_revision = _expected_revision(payload)
        if str(row["status"] or "") == "closed":
            if expected_revision != actual_revision:
                conn.execute("ROLLBACK")
                raise DesktopSessionRevisionConflict(expected_revision, actual_revision)
            conn.execute("COMMIT")
            return _public_session(row)
        if expected_revision != actual_revision:
            conn.execute("ROLLBACK")
            raise DesktopSessionRevisionConflict(expected_revision, actual_revision)
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


def get_desktop_session(desktop_session_id: str) -> dict[str, Any]:
    normalized_id = _safe_text(desktop_session_id, max_length=160)
    if not normalized_id:
        return {}
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM desktop_sessions WHERE desktop_session_id = ?",
            (normalized_id,),
        ).fetchone()
    return _public_session(row)


def latest_active_desktop_session(
    *,
    provider: str = "",
    workspace_root: str = "",
    window_role: str = "",
) -> dict[str, Any]:
    """Return the newest live desktop session matching the optional scope.

    Lease, provider, workspace, and window-role conditions are pushed into
    SQL before the LIMIT, so newer unrelated rows can no longer shadow a
    valid target. Python-side checks remain as a defensive second layer.
    """

    normalized_provider = _safe_text(provider, max_length=80)
    normalized_window_role = _safe_text(window_role, max_length=80)
    normalized_workspace = _normalize_workspace_root(workspace_root)
    lease_cutoff = (
        datetime.now(timezone.utc)
        - timedelta(seconds=DESKTOP_SESSION_HEARTBEAT_LEASE_SECONDS)
    ).isoformat()
    clauses = ["status = 'active'", "last_heartbeat_at >= ?"]
    parameters: list[str] = [lease_cutoff]
    if normalized_provider:
        clauses.append("provider = ?")
        parameters.append(normalized_provider)
    if normalized_workspace:
        clauses.append("replace(lower(workspace_root), '/', '\\') = ?")
        parameters.append(normalized_workspace)
    if normalized_window_role:
        clauses.append("json_type(windows_json, '$.' || ?) = 'object'")
        parameters.append(normalized_window_role)
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM desktop_sessions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY last_heartbeat_at DESC, updated_at DESC LIMIT 32",
                parameters,
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {}
    for row in rows:
        if not _lease_active(row):
            continue
        if normalized_provider and _safe_text(row["provider"], max_length=80) != normalized_provider:
            continue
        if normalized_workspace and _normalize_workspace_root(row["workspace_root"]) != normalized_workspace:
            continue
        if normalized_window_role:
            try:
                windows = json.loads(str(row["windows_json"] or "{}"))
            except json.JSONDecodeError:
                windows = {}
            if not isinstance(windows.get(normalized_window_role), dict):
                continue
        return _public_session(row)
    return {}


def latest_active_desktop_window(role: str) -> dict[str, Any]:
    normalized_role = _safe_text(role, max_length=80)
    if normalized_role not in WINDOW_ROLES:
        raise ValueError(f"unsupported desktop session window role: {normalized_role}")
    session = latest_active_desktop_session(window_role=normalized_role)
    if session:
        window = session.get("windows", {}).get(normalized_role)
        if isinstance(window, dict):
            return {
                **window,
                "desktopSessionId": session["desktopSessionId"],
                "desktopSessionRevision": int(session["revision"] or 0),
                "desktopSessionLeaseExpiresAt": str(session["leaseExpiresAt"] or ""),
            }
    return {}


def latest_active_window_provider_projection(*, workspace_root: str = "") -> dict[str, Any]:
    """Project the active Electron session, including launcher-only sessions."""

    try:
        session = latest_active_desktop_session(provider="electron", workspace_root=workspace_root)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {}
    if not session:
        return {}
    windows = session.get("windows") if isinstance(session.get("windows"), dict) else {}
    workbench = windows.get("workbench") if isinstance(windows.get("workbench"), dict) else {}
    is_open = bool(workbench.get("open", False))
    projection: dict[str, Any] = {
        "browserWindowAlive": is_open,
        "browserManaged": False,
        "windowProvider": "electron",
        "windowManaged": is_open,
        "windowId": int(workbench.get("windowId") or 0),
        "rendererProcessId": int(workbench.get("rendererProcessId") or 0),
        "url": str(workbench.get("url") or "").strip(),
        "desktopSessionId": str(session.get("desktopSessionId") or "").strip(),
        "desktopSessionRevision": int(session.get("revision") or 0),
        "desktopSessionLeaseExpiresAt": str(session.get("leaseExpiresAt") or "").strip(),
    }
    if workbench:
        projection["observedState"] = "open" if is_open else "closed"
    return projection


def latest_active_workbench_projection() -> dict[str, Any]:
    """Project the current Electron workbench into the shared window contract."""

    try:
        window = latest_active_desktop_window("workbench")
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {}
    if not window:
        return {}
    is_open = bool(window.get("open", False))
    return {
        "observedState": "open" if is_open else "closed",
        "browserWindowAlive": is_open,
        "browserManaged": False,
        "windowProvider": "electron",
        "windowManaged": is_open,
        "windowId": int(window.get("windowId") or 0),
        "rendererProcessId": int(window.get("rendererProcessId") or 0),
        "url": str(window.get("url") or "").strip(),
        "desktopSessionId": str(window.get("desktopSessionId") or "").strip(),
        "desktopSessionRevision": int(window.get("desktopSessionRevision") or 0),
        "desktopSessionLeaseExpiresAt": str(window.get("desktopSessionLeaseExpiresAt") or "").strip(),
    }


def _normalize_workspace_root(value: Any) -> str:
    raw = _safe_text(value, max_length=1000)
    if not raw:
        return ""
    try:
        return os.path.normcase(os.path.abspath(raw)).rstrip("\\/")
    except (OSError, TypeError, ValueError):
        return raw.casefold().rstrip("\\/")


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


def _expected_revision(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        raise ValueError("desktop session revision is required")
    revision = _safe_int(payload.get("revision"))
    if revision <= 0:
        raise ValueError("desktop session revision is required")
    return revision


def _require_open_revision(row: sqlite3.Row, payload: dict[str, Any]) -> None:
    actual_revision = int(row["revision"] or 0)
    if str(row["status"] or "") == "closed":
        raise DesktopSessionClosed(str(row["desktop_session_id"] or ""), actual_revision)
    expected_revision = _expected_revision(payload)
    if expected_revision != actual_revision:
        raise DesktopSessionRevisionConflict(expected_revision, actual_revision)


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
