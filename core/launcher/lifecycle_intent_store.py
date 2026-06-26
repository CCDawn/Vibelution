from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.runtime_manager.constants import PROJECT_ROOT


LIFECYCLE_DB_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "lifecycle.sqlite3"
DESKTOP_ACTIONS = {"open_workbench", "focus_workbench", "close_workbench"}
RUNTIME_EFFECT_ACTIONS = {"restart_after_apply", "resume_self_evolution", "recover_after_crash", "request_app_exit"}
ALLOWED_ACTIONS = DESKTOP_ACTIONS | RUNTIME_EFFECT_ACTIONS
TERMINAL_INTENT_STATUSES = {"succeeded", "failed", "superseded"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, max_length: int = 500) -> str:
    return str(value or "").strip()[:max_length]


def _connect() -> sqlite3.Connection:
    LIFECYCLE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LIFECYCLE_DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lifecycle_intents (
          intent_id TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          action TEXT NOT NULL,
          status TEXT NOT NULL,
          actor_type TEXT NOT NULL,
          actor_id TEXT NOT NULL,
          reason TEXT NOT NULL,
          source_run_id TEXT NOT NULL,
          source_task_id TEXT NOT NULL,
          source_worktree TEXT NOT NULL,
          idempotency_key TEXT NOT NULL UNIQUE,
          rejection_reason TEXT NOT NULL DEFAULT '',
          command_id TEXT NOT NULL DEFAULT '',
          runtime_scene_ref TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '{}',
          completed_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS desktop_actions (
          action_id TEXT PRIMARY KEY,
          intent_id TEXT NOT NULL REFERENCES lifecycle_intents(intent_id),
          action TEXT NOT NULL,
          status TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          claimed_by TEXT NOT NULL DEFAULT '',
          claimed_at TEXT NOT NULL DEFAULT '',
          lease_expires_at TEXT NOT NULL DEFAULT '',
          claim_attempt INTEGER NOT NULL DEFAULT 0,
          result_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_desktop_actions_claim
          ON desktop_actions(status, lease_expires_at, created_at);
        """
    )
    _ensure_column(conn, "lifecycle_intents", "result_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "lifecycle_intents", "completed_at", "TEXT NOT NULL DEFAULT ''")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def submit_lifecycle_intent(
    payload: dict[str, Any],
    *,
    actor_context: dict[str, Any],
    active_work_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    action = _safe_text(payload.get("action"), max_length=80)
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported lifecycle intent action: {action}")
    idempotency_key = _safe_text(payload.get("idempotencyKey"), max_length=240)
    if not idempotency_key:
        raise ValueError("lifecycle intent idempotencyKey is required")
    now = _now_iso()
    active_work_running = bool(active_work_runs) and action in RUNTIME_EFFECT_ACTIONS
    intent_id = f"intent-{uuid4().hex}"
    status = "rejected" if active_work_running else "accepted"
    intent = {
        "intentId": intent_id,
        "schemaVersion": 1,
        "action": action,
        "status": status,
        "actorType": _safe_text(actor_context.get("actorType"), max_length=80),
        "actorId": _safe_text(actor_context.get("actorId"), max_length=160),
        "reason": _safe_text(payload.get("reason"), max_length=300),
        "sourceRunId": _safe_text(actor_context.get("sourceRunId"), max_length=160),
        "sourceTaskId": _safe_text(actor_context.get("sourceTaskId"), max_length=160),
        "sourceWorktree": _safe_text(actor_context.get("sourceWorktree")),
        "idempotencyKey": idempotency_key,
        "createdAt": now,
        "updatedAt": now,
        "rejectionReason": "active_work_running" if active_work_running else "",
        "commandId": "",
        "runtimeSceneRef": "",
    }
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM lifecycle_intents WHERE idempotency_key = ?",
            (intent["idempotencyKey"],),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return _public_intent(_row_to_dict(existing))
        conn.execute(
            """
            INSERT INTO lifecycle_intents (
              intent_id, schema_version, action, status, actor_type, actor_id, reason,
              source_run_id, source_task_id, source_worktree, idempotency_key,
              rejection_reason, command_id, runtime_scene_ref, result_json, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_id,
                1,
                action,
                status,
                intent["actorType"],
                intent["actorId"],
                intent["reason"],
                intent["sourceRunId"],
                intent["sourceTaskId"],
                intent["sourceWorktree"],
                intent["idempotencyKey"],
                intent["rejectionReason"],
                "",
                "",
                "{}",
                "",
                now,
                now,
            ),
        )
        if status == "accepted" and action in DESKTOP_ACTIONS:
            conn.execute(
                """
                INSERT INTO desktop_actions (
                  action_id, intent_id, action, status, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    f"desktop-action-{uuid4().hex}",
                    intent_id,
                    action,
                    json.dumps(
                        {"sourceRunId": intent["sourceRunId"], "sourceTaskId": intent["sourceTaskId"]},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
        conn.execute("COMMIT")
    return intent


def get_lifecycle_intent(intent_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lifecycle_intents WHERE intent_id = ?",
            (_safe_text(intent_id, max_length=160),),
        ).fetchone()
    return _public_intent(_row_to_dict(row))


def record_runtime_dispatch(intent_id: str, *, command_id: str, runtime_scene_ref: str = "") -> dict[str, Any]:
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE lifecycle_intents
            SET status = CASE
                    WHEN status IN ('accepted', 'executing') THEN 'executing'
                    ELSE status
                END,
                command_id = ?,
                runtime_scene_ref = ?,
                updated_at = ?
            WHERE intent_id = ?
            """,
            (_safe_text(command_id, max_length=160), _safe_text(runtime_scene_ref, max_length=300), now, intent_id),
        )
        row = conn.execute("SELECT * FROM lifecycle_intents WHERE intent_id = ?", (intent_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_intent(_row_to_dict(row))


def complete_lifecycle_intent(intent_id: str, *, status: str, result: dict[str, Any]) -> dict[str, Any]:
    normalized_status = _safe_text(status, max_length=80)
    if normalized_status not in TERMINAL_INTENT_STATUSES:
        raise ValueError(f"unsupported lifecycle terminal status: {status}")
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _complete_lifecycle_intent_locked(
            conn,
            intent_id=_safe_text(intent_id, max_length=160),
            status=normalized_status,
            result=result,
            now=now,
        )
        row = conn.execute("SELECT * FROM lifecycle_intents WHERE intent_id = ?", (intent_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_intent(_row_to_dict(row))


def _complete_lifecycle_intent_locked(
    conn: sqlite3.Connection,
    *,
    intent_id: str,
    status: str,
    result: dict[str, Any],
    now: str,
) -> None:
    conn.execute(
        """
        UPDATE lifecycle_intents
        SET status = ?,
            result_json = ?,
            completed_at = ?,
            updated_at = ?
        WHERE intent_id = ?
        """,
        (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now, now, intent_id),
    )


def _public_intent(row: dict[str, Any]) -> dict[str, Any]:
    result_raw = row.get("result_json") or "{}"
    try:
        result = json.loads(str(result_raw))
    except json.JSONDecodeError:
        result = {}
    return {
        "intentId": row.get("intent_id"),
        "schemaVersion": int(row.get("schema_version") or 1),
        "action": row.get("action"),
        "status": row.get("status"),
        "rejectionReason": row.get("rejection_reason") or "",
        "commandId": row.get("command_id") or "",
        "runtimeSceneRef": row.get("runtime_scene_ref") or "",
        "result": result if isinstance(result, dict) else {},
        "completedAt": row.get("completed_at") or "",
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def claim_desktop_action(*, desktop_session_id: str, lease_seconds: int = 30) -> dict[str, Any]:
    now = _now_iso()
    lease_expires_at = datetime.now(timezone.utc).timestamp() + max(1, int(lease_seconds))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _fail_exhausted_desktop_actions_locked(conn, now=now)
        row = conn.execute(
            """
            SELECT * FROM desktop_actions
            WHERE status = 'pending' OR (status = 'claimed' AND lease_expires_at < ? AND claim_attempt < 3)
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return {}
        action_id = str(row["action_id"])
        expires_iso = datetime.fromtimestamp(lease_expires_at, tz=timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE desktop_actions
            SET status = 'claimed',
                claimed_by = ?,
                claimed_at = ?,
                lease_expires_at = ?,
                claim_attempt = claim_attempt + 1,
                updated_at = ?
            WHERE action_id = ?
            """,
            (_safe_text(desktop_session_id, max_length=160), now, expires_iso, now, action_id),
        )
        claimed = conn.execute("SELECT * FROM desktop_actions WHERE action_id = ?", (action_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_desktop_action(claimed)


def _fail_exhausted_desktop_actions_locked(conn: sqlite3.Connection, *, now: str) -> None:
    rows = conn.execute(
        """
        SELECT * FROM desktop_actions
        WHERE status = 'claimed' AND lease_expires_at < ? AND claim_attempt >= 3
        """,
        (now,),
    ).fetchall()
    for row in rows:
        result = {
            "reason": "desktop_action_retry_exhausted",
            "claimAttempt": int(row["claim_attempt"] or 0),
        }
        conn.execute(
            """
            UPDATE desktop_actions
            SET status = 'failed',
                result_json = ?,
                updated_at = ?
            WHERE action_id = ?
            """,
            (json.dumps(result, ensure_ascii=False, sort_keys=True), now, row["action_id"]),
        )
        _complete_lifecycle_intent_locked(
            conn,
            intent_id=str(row["intent_id"] or ""),
            status="failed",
            result=result,
            now=now,
        )


def ack_desktop_action(action_id: str, *, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return _finish_desktop_action(action_id, desktop_session_id=desktop_session_id, status="succeeded", result=result)


def fail_desktop_action(action_id: str, *, desktop_session_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return _finish_desktop_action(action_id, desktop_session_id=desktop_session_id, status="failed", result=result)


def _finish_desktop_action(action_id: str, *, desktop_session_id: str, status: str, result: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM desktop_actions WHERE action_id = ? AND status = 'claimed' AND claimed_by = ?",
            (_safe_text(action_id, max_length=160), _safe_text(desktop_session_id, max_length=160)),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return {}
        conn.execute(
            """
            UPDATE desktop_actions
            SET status = ?, result_json = ?, updated_at = ?
            WHERE action_id = ?
            """,
            (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now, action_id),
        )
        _complete_lifecycle_intent_locked(
            conn,
            intent_id=str(row["intent_id"] or ""),
            status=status,
            result=result,
            now=now,
        )
        updated = conn.execute("SELECT * FROM desktop_actions WHERE action_id = ?", (action_id,)).fetchone()
        conn.execute("COMMIT")
    return _public_desktop_action(updated)


def _public_desktop_action(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "actionId": row["action_id"],
        "intentId": row["intent_id"],
        "action": row["action"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"]),
        "claimedBy": row["claimed_by"],
        "leaseExpiresAt": row["lease_expires_at"],
        "claimAttempt": int(row["claim_attempt"] or 0),
        "result": json.loads(row["result_json"] or "{}"),
    }
