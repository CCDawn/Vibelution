"""SQLite dispatch-receipt ledger for the personal assistant (批三地基).

The authoritative inbox JSONL rows stay untouched: this ledger is a
delivery-side observer that extracts the pairing envelope
(``replyToMessageId`` / ``paFollowupOfMessageId`` / ``paFollowupRound`` /
``personalAssistantTask``) into explicit columns at write time, so pairing
no longer dies silently when an oversized ``agentToolMetadataJson``
envelope is dropped by the JSONL read path. Read-side fallback semantics
are unchanged there; only newly recorded rows become immune.

Single-writer discipline: every mutation is one ``BEGIN IMMEDIATE``
transaction on a connection opened per operation (no pinned handles —
native Windows handles holding SQLite leaves are a reminder-ledger-only
concern). Replays are safe: ``INSERT ... ON CONFLICT(message_id) DO
UPDATE`` merges monotonically (pending < consumed < revoked; digest
markers never regress). Hygiene mirrors ``reminder_receipts``: STRICT
tables, CHECK constraints, a ``user_version`` migration, PERSIST journal
with ``synchronous=FULL``, a bounded busy-timeout gradient and a
``quick_check`` gate taken once before the ledger is first trusted for
reads (per-message writes stay O(1) afterwards).

Pairing parity with the JSONL read model requires two ledger-only
concepts. ``inbox_agent_id`` records which agent's inbox a row was
harvested from, so thread/chase matching stays authoritative. And
``dispatch_instances`` carries one row per JSONL row occurrence, because
the JSONL window counts instances — a duplicated id occupies two window
slots and only pairs while exactly one instance is visible — while a
PRIMARY KEY would silently deduplicate them.

The backfill is change-driven, not one-shot: inbox file signatures
(mtime_ns, size) are stored per harvest and any change re-harvests all
inboxes (bounded caps), because inbox JSONLs are also mutated by writers
that bypass this process's hooks. Harvest completeness is tracked; a
degraded scan must never feed a uniqueness proof. Observers never raise:
a ledger failure must never break an inbox write, and the read model
falls back to the legacy JSONL scan when the ledger cannot serve a view.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import debug as _debug_logger

LEDGER_DIR_NAME = "pa_dispatch_ledger"
LEDGER_FILENAME = "dispatch_ledger.sqlite3"
SCHEMA_VERSION = 1

# Rows scanned per inbox during harvest. Twice the read model's largest
# window keeps the newest dispatch population complete while the cost
# stays bounded on chatty workspaces.
_HARVEST_TARGET_INBOX_CAP = 400
_HARVEST_ASSISTANT_INBOX_CAP = 800
# Envelope parsing at write time has no 8192 limit (that limit is a JSONL
# read-path survival rule); the bound only rejects pathological payloads so
# one row cannot stall the delivery path.
_ENVELOPE_PARSE_MAX_CHARS = 262144
# Refuse to slurp pathological inbox files during harvest; the inbox is
# then marked incomplete (same defensive outcome as a read failure).
_HARVEST_MAX_FILE_BYTES = 64 * 1024 * 1024
# Forward reads stop at this line bound: a stream that never reaches EOF
# (or a hostile line source) cannot hang the delivery path, and an
# unbounded file is already covered by the size guard (both degrade to an
# incomplete harvest).
_HARVEST_MAX_LINES = 100_000
_BUSY_TIMEOUT_STEPS_MS = (250, 1000, 2000)
_PA_ID_MEMO_TTL_SECONDS = 5.0

_DISPATCH_KIND = "dispatch"
_FOLLOWUP_KIND_ROW = "followup"
_REPLY_KIND = "agent_inbox_reply"
_FOLLOWUP_KIND = "pa_followup"
_ENVELOPE_KEYS = (
    "replyToMessageId",
    "paFollowupOfMessageId",
    "paFollowupRound",
    "personalAssistantTask",
)

_META_SQL = """CREATE TABLE ledger_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    pa_agent_id TEXT NOT NULL DEFAULT '',
    backfill_at TEXT NOT NULL DEFAULT ''
) STRICT"""
_DISPATCHES_SQL = """CREATE TABLE dispatches (
    message_id TEXT PRIMARY KEY,
    row_kind TEXT NOT NULL CHECK(row_kind IN ('dispatch','followup')),
    source_agent_id TEXT NOT NULL,
    target_agent_id TEXT NOT NULL,
    inbox_agent_id TEXT NOT NULL DEFAULT '',
    target_session_id TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    target_agent_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending','consumed','revoked')),
    sent_at TEXT NOT NULL,
    sent_at_ms INTEGER NOT NULL CHECK(sent_at_ms >= 0),
    task_status TEXT CHECK(task_status IS NULL OR task_status IN
        ('running','blocked','completed','failed')),
    followup_round INTEGER,
    followup_at TEXT,
    pa_followup_of_message_id TEXT NOT NULL DEFAULT '',
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
) STRICT"""
# One row per JSONL row occurrence (duplicated ids occupy several slots).
# Rebuilt wholesale at each harvest; the read view derives its instance-
# accurate window and per-id visibility counts from it.
_INSTANCES_SQL = """CREATE TABLE dispatch_instances (
    inbox_agent_id TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL,
    sent_at_ms INTEGER NOT NULL CHECK(sent_at_ms >= 0),
    sort_message_id TEXT NOT NULL DEFAULT ''
) STRICT"""
_RECEIPTS_SQL = """CREATE TABLE receipts (
    message_id TEXT PRIMARY KEY,
    source_agent_id TEXT NOT NULL DEFAULT '',
    target_agent_id TEXT NOT NULL DEFAULT '',
    inbox_agent_id TEXT NOT NULL DEFAULT '',
    target_session_id TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    source_agent_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending','consumed','revoked')),
    reply_to_message_id TEXT NOT NULL DEFAULT '',
    pa_followup_of_message_id TEXT NOT NULL DEFAULT '',
    pa_followup_round INTEGER,
    personal_assistant_task TEXT CHECK(personal_assistant_task IS NULL OR
        json_valid(personal_assistant_task)),
    received_at TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL CHECK(received_at_ms >= 0),
    digested_at TEXT,
    updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms >= 0)
) STRICT"""
# Per-inbox harvest bookkeeping: the signature drives change-detection and
# the completeness flag fences uniqueness proofs off degraded scans.
_HARVEST_SQL = """CREATE TABLE harvest_state (
    agent_id TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL CHECK(mtime_ns >= 0),
    size INTEGER NOT NULL CHECK(size >= 0),
    complete INTEGER NOT NULL CHECK(complete IN (0,1))
) STRICT"""
_INDEX_SQL = (
    """CREATE INDEX idx_dispatches_window
       ON dispatches(row_kind, sent_at_ms DESC, message_id DESC)""",
    """CREATE INDEX idx_dispatches_thread
       ON dispatches(target_agent_id, thread_id, row_kind)""",
    """CREATE INDEX idx_receipts_reply
       ON receipts(reply_to_message_id, received_at_ms DESC)""",
    """CREATE INDEX idx_receipts_window
       ON receipts(received_at_ms DESC, message_id DESC)""",
    """CREATE INDEX idx_receipts_thread
       ON receipts(source_agent_id, thread_id, received_at_ms DESC)""",
    """CREATE INDEX idx_dispatch_instances_message
       ON dispatch_instances(message_id)""",
)


class DispatchLedgerUnavailableError(Exception):
    """The ledger cannot be opened or migrated; callers fall back to JSONL."""


# ---------------------------------------------------------------------------
# Path / connection hygiene
# ---------------------------------------------------------------------------


def ledger_database_path() -> Path:
    """Workspace-routed ledger path (same routing as every workspace file)."""

    from core.web.services import agent_directory_service as directory

    return directory._workspace_path(
        LEDGER_DIR_NAME, LEDGER_FILENAME, intent="state", seed=False
    )


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=0.05, isolation_level=None)
    connection.execute("PRAGMA journal_mode=PERSIST")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA trusted_schema=OFF")
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise DispatchLedgerUnavailableError("dispatch_ledger_schema_ahead")
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        if version == 0:
            if names:
                # A non-empty v0 database is a foreign or corrupted file.
                raise DispatchLedgerUnavailableError("dispatch_ledger_schema_invalid")
            connection.execute(_META_SQL)
            connection.execute(_DISPATCHES_SQL)
            connection.execute(_RECEIPTS_SQL)
            connection.execute(_INSTANCES_SQL)
            connection.execute(_HARVEST_SQL)
            for statement in _INDEX_SQL:
                connection.execute(statement)
            connection.execute("INSERT INTO ledger_meta(singleton) VALUES (1)")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == SCHEMA_VERSION:
            if not {
                "ledger_meta", "dispatches", "receipts", "dispatch_instances",
                "harvest_state",
            }.issubset(names):
                raise DispatchLedgerUnavailableError("dispatch_ledger_schema_invalid")
        else:
            raise DispatchLedgerUnavailableError("dispatch_ledger_schema_invalid")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _open_writable() -> sqlite3.Connection:
    """Open with a busy-timeout gradient; each step re-opens on a fresh
    connection (retrying beats spinning inside one contended handle)."""

    path = ledger_database_path()
    last_error: Exception | None = None
    for step, timeout_ms in enumerate(_BUSY_TIMEOUT_STEPS_MS):
        try:
            connection = _connect(path)
            connection.execute(f"PRAGMA busy_timeout={timeout_ms}")
            _migrate(connection)
            return connection
        except sqlite3.OperationalError as exc:
            last_error = exc
            time.sleep(0.02 * (step + 1))
    raise DispatchLedgerUnavailableError(f"dispatch_ledger_busy ({type(last_error).__name__})")


def _open_readable() -> sqlite3.Connection:
    path = ledger_database_path()
    if not path.exists():
        raise DispatchLedgerUnavailableError("dispatch_ledger_missing")
    connection = _connect(path)
    connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_STEPS_MS[-1]}")
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        connection.close()
        raise DispatchLedgerUnavailableError("dispatch_ledger_schema_invalid")
    return connection


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _text(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "").strip()


def _iso_to_ms(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int(parsed.timestamp() * 1000))


def _merged_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Native metadata plus the four envelope keys, without the 8192 cap.

    The JSONL read path drops oversized envelopes; the ledger records them
    while the row is still in memory, before any read-path survival rule.
    """

    native = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    result = dict(native)
    encoded = native.get("agentToolMetadataJson")
    if not isinstance(encoded, str) or not encoded.strip():
        return result
    if len(encoded) > _ENVELOPE_PARSE_MAX_CHARS:
        _debug_logger.warning(
            "Dispatch ledger skipped an oversized tool metadata envelope. "
            f"length={len(encoded)}"
        )
        return result
    try:
        custom = json.loads(encoded)
    except (ValueError, RecursionError):
        return result
    if isinstance(custom, dict):
        for key in _ENVELOPE_KEYS:
            if key not in result and key in custom:
                result[key] = custom[key]
    return result


_PA_ID_MEMO: dict[str, Any] = {"key": None, "expires": 0.0, "value": ""}
_PA_ID_MEMO_LOCK = threading.Lock()


def reset_identity_memo() -> None:
    """Drop the cached PA identity so the next probe re-reads the profile."""

    with _PA_ID_MEMO_LOCK:
        _PA_ID_MEMO.update({"key": None, "expires": 0.0, "value": ""})


def _pa_agent_id_cached() -> str:
    from core.web.services import agent_directory_service as directory
    from core.web.services import personal_assistant_service as pa_service

    try:
        root = str(directory._active_project_root())
    except Exception:
        root = ""
    now = time.monotonic()
    with _PA_ID_MEMO_LOCK:
        if _PA_ID_MEMO["key"] == root and now < float(_PA_ID_MEMO["expires"]):
            return str(_PA_ID_MEMO["value"])
    try:
        agent = pa_service.profile_agent()
    except Exception:
        agent = None
    value = _text(agent or {}, "agentId")
    with _PA_ID_MEMO_LOCK:
        _PA_ID_MEMO.update(
            {"key": root, "expires": now + _PA_ID_MEMO_TTL_SECONDS, "value": value}
        )
    return value


def _is_followup_row(kind: str, metadata: dict[str, Any]) -> bool:
    return kind == _FOLLOWUP_KIND or bool(_text(metadata, "paFollowupOfMessageId"))


def _classify(row: dict[str, Any], assistant_agent_id: str) -> str:
    """Mirror the read model's row taxonomy: dispatch / followup / receipt."""

    source = _text(row, "sourceAgentId")
    target = _text(row, "targetAgentId")
    kind = _text(row, "kind")
    metadata = _merged_metadata(row)
    if source == assistant_agent_id and _is_followup_row(kind, metadata):
        return _FOLLOWUP_KIND_ROW
    if (
        source == assistant_agent_id
        and target != assistant_agent_id
        and kind != _REPLY_KIND
    ):
        return _DISPATCH_KIND
    if target == assistant_agent_id:
        return "receipt"
    return ""


def _followup_round(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("paFollowupRound")
    if type(value) is int and value >= 0:
        return value
    return None


def _task_json(metadata: dict[str, Any]) -> str | None:
    task = metadata.get("personalAssistantTask")
    if not isinstance(task, dict):
        return None
    try:
        return json.dumps(task, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return None


def _parse_task(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        task = json.loads(raw)
    except ValueError:
        return None
    return task if isinstance(task, dict) else None


# ---------------------------------------------------------------------------
# Recording (write-side observers; never raise)
# ---------------------------------------------------------------------------


def _status_merge_sql(table: str) -> str:
    """Monotonic status merge: replayed pending rows must never downgrade
    an already consumed/revoked ledger row. ``table`` must name the upsert
    target so the qualified reference stays valid on both tables."""

    return f"""status=CASE
    WHEN excluded.status='revoked' OR {table}.status='revoked' THEN 'revoked'
    WHEN excluded.status='consumed' OR {table}.status='consumed' THEN 'consumed'
    ELSE 'pending'
END"""


_DISPATCH_STATUS_MERGE = _status_merge_sql("dispatches")
_RECEIPT_STATUS_MERGE = _status_merge_sql("receipts")


def _upsert_dispatch(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    metadata: dict[str, Any],
    inbox_agent_id: str,
    now_ms: int,
) -> None:
    status = _text(row, "status").lower()
    if status not in {"pending", "consumed", "revoked"}:
        status = "pending"
    connection.execute(
        f"""
        INSERT INTO dispatches (
            message_id, row_kind, source_agent_id, target_agent_id,
            inbox_agent_id, target_session_id, source_session_id, thread_id,
            kind, summary, target_agent_name, status, sent_at, sent_at_ms,
            task_status, followup_round, followup_at, pa_followup_of_message_id,
            updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, '', ?)
        ON CONFLICT(message_id) DO UPDATE SET
            row_kind=excluded.row_kind,
            source_agent_id=excluded.source_agent_id,
            target_agent_id=excluded.target_agent_id,
            inbox_agent_id=excluded.inbox_agent_id,
            target_session_id=excluded.target_session_id,
            source_session_id=excluded.source_session_id,
            thread_id=excluded.thread_id,
            kind=excluded.kind,
            summary=excluded.summary,
            target_agent_name=excluded.target_agent_name,
            {_DISPATCH_STATUS_MERGE},
            sent_at=excluded.sent_at,
            sent_at_ms=excluded.sent_at_ms,
            updated_at_ms=excluded.updated_at_ms
        """,
        (
            _text(row, "messageId") or _text(row, "eventId"),
            _DISPATCH_KIND,
            _text(row, "sourceAgentId"),
            _text(row, "targetAgentId"),
            inbox_agent_id,
            _text(row, "targetSessionId"),
            _text(metadata, "sourceSessionId"),
            _text(row, "threadId"),
            _text(row, "kind"),
            _text(row, "summary"),
            _text(row, "targetAgentName"),
            status,
            _text(row, "createdAt"),
            _iso_to_ms(_text(row, "createdAt")),
            now_ms,
        ),
    )


def _upsert_followup(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    metadata: dict[str, Any],
    inbox_agent_id: str,
    now_ms: int,
) -> None:
    status = _text(row, "status").lower()
    if status not in {"pending", "consumed", "revoked"}:
        status = "pending"
    connection.execute(
        """
        INSERT INTO dispatches (
            message_id, row_kind, source_agent_id, target_agent_id,
            inbox_agent_id, target_session_id, source_session_id, thread_id,
            kind, summary, target_agent_name, status, sent_at, sent_at_ms,
            task_status, followup_round, followup_at, pa_followup_of_message_id,
            updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            row_kind=excluded.row_kind,
            target_agent_id=excluded.target_agent_id,
            inbox_agent_id=excluded.inbox_agent_id,
            target_session_id=excluded.target_session_id,
            source_session_id=excluded.source_session_id,
            thread_id=excluded.thread_id,
            summary=excluded.summary,
            status=CASE WHEN dispatches.status='revoked' THEN 'revoked'
                        ELSE excluded.status END,
            sent_at=excluded.sent_at,
            sent_at_ms=excluded.sent_at_ms,
            followup_round=excluded.followup_round,
            pa_followup_of_message_id=excluded.pa_followup_of_message_id,
            updated_at_ms=excluded.updated_at_ms
        """,
        (
            _text(row, "messageId") or _text(row, "eventId"),
            _FOLLOWUP_KIND_ROW,
            _text(row, "sourceAgentId"),
            _text(row, "targetAgentId"),
            inbox_agent_id,
            _text(row, "targetSessionId"),
            _text(metadata, "sourceSessionId"),
            _text(row, "threadId"),
            _text(row, "kind"),
            _text(row, "summary"),
            _text(row, "targetAgentName"),
            status,
            _text(row, "createdAt"),
            _iso_to_ms(_text(row, "createdAt")),
            _followup_round(metadata),
            _text(metadata, "paFollowupOfMessageId"),
            now_ms,
        ),
    )


def _chase_origin(
    connection: sqlite3.Connection,
    *,
    origin_id: str,
    followup_at: str,
    followup_round: int | None,
) -> None:
    """Stamp the chased dispatch with the latest follow-up round/time."""

    if not origin_id:
        return
    connection.execute(
        """
        UPDATE dispatches
        SET followup_round=COALESCE(?, followup_round),
            followup_at=?
        WHERE message_id=? AND row_kind='dispatch'
        """,
        (followup_round, followup_at, origin_id),
    )


def _upsert_receipt(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    metadata: dict[str, Any],
    inbox_agent_id: str,
    now_ms: int,
) -> None:
    status = _text(row, "status").lower()
    if status not in {"pending", "consumed", "revoked"}:
        status = "pending"
    task_report = metadata.get("personalAssistantTask")
    task_status = None
    if isinstance(task_report, dict):
        reported = str(task_report.get("status") or "").strip()
        if reported in {"running", "blocked", "completed", "failed"}:
            task_status = reported
    connection.execute(
        f"""
        INSERT INTO receipts (
            message_id, source_agent_id, target_agent_id, inbox_agent_id,
            target_session_id, source_session_id, thread_id, kind, summary,
            source_agent_name, status, reply_to_message_id,
            pa_followup_of_message_id, pa_followup_round,
            personal_assistant_task, received_at, received_at_ms, digested_at,
            updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            source_agent_id=excluded.source_agent_id,
            target_agent_id=excluded.target_agent_id,
            inbox_agent_id=excluded.inbox_agent_id,
            target_session_id=excluded.target_session_id,
            source_session_id=excluded.source_session_id,
            thread_id=excluded.thread_id,
            kind=excluded.kind,
            summary=excluded.summary,
            source_agent_name=excluded.source_agent_name,
            {_RECEIPT_STATUS_MERGE},
            reply_to_message_id=CASE WHEN excluded.reply_to_message_id != ''
                THEN excluded.reply_to_message_id ELSE receipts.reply_to_message_id END,
            pa_followup_of_message_id=CASE WHEN excluded.pa_followup_of_message_id != ''
                THEN excluded.pa_followup_of_message_id ELSE receipts.pa_followup_of_message_id END,
            pa_followup_round=COALESCE(excluded.pa_followup_round, receipts.pa_followup_round),
            personal_assistant_task=COALESCE(excluded.personal_assistant_task,
                receipts.personal_assistant_task),
            received_at=excluded.received_at,
            received_at_ms=excluded.received_at_ms,
            digested_at=receipts.digested_at,
            updated_at_ms=excluded.updated_at_ms
        """,
        (
            _text(row, "messageId") or _text(row, "eventId"),
            _text(row, "sourceAgentId"),
            _text(row, "targetAgentId"),
            inbox_agent_id,
            _text(row, "targetSessionId"),
            _text(metadata, "sourceSessionId"),
            _text(row, "threadId"),
            _text(row, "kind"),
            _text(row, "summary"),
            _text(row, "sourceAgentName"),
            status,
            _text(metadata, "replyToMessageId"),
            _text(metadata, "paFollowupOfMessageId"),
            _followup_round(metadata),
            _task_json(metadata),
            _text(row, "createdAt"),
            _iso_to_ms(_text(row, "createdAt")),
            now_ms,
        ),
    )
    # Materialize the latest explicit report onto the chased dispatch. The
    # read model re-derives task status from receipts anyway; the column is
    # an audit trail of the last accepted report in arrival order.
    reply_to = _text(metadata, "replyToMessageId")
    if task_status and reply_to:
        connection.execute(
            """
            UPDATE dispatches SET task_status=?
            WHERE message_id=? AND row_kind='dispatch'
            """,
            (task_status, reply_to),
        )


def _record_row(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    assistant_agent_id: str,
    now_ms: int,
    *,
    inbox_agent_id: str = "",
) -> None:
    """Classify and upsert one inbox row.

    ``inbox_agent_id`` is the authoritative inbox owner: hook-recorded rows
    are delivered to ``targetAgentId``; harvest passes the agent whose
    inbox file was scanned, so a foreign row never passes an authority
    check downstream.
    """

    classification = _classify(row, assistant_agent_id)
    if not classification:
        return
    metadata = _merged_metadata(row)
    owner = inbox_agent_id or _text(row, "targetAgentId")
    if classification == "receipt":
        _upsert_receipt(connection, row, metadata, owner, now_ms)
    elif classification == _DISPATCH_KIND:
        _upsert_dispatch(connection, row, metadata, owner, now_ms)
    else:
        _upsert_followup(connection, row, metadata, owner, now_ms)
        _chase_origin(
            connection,
            origin_id=_text(metadata, "paFollowupOfMessageId"),
            followup_at=_text(row, "createdAt"),
            followup_round=_followup_round(metadata),
        )


def record_inbox_message(row: dict[str, Any]) -> None:
    """Delivery-side observer: record one inbox row if it involves the PA.

    Never raises. Classification happens while the envelope is still in
    memory, so oversized ``agentToolMetadataJson`` payloads still land in
    the explicit pairing columns.
    """

    try:
        if not isinstance(row, dict):
            return
        assistant_agent_id = _pa_agent_id_cached()
        if not assistant_agent_id:
            return
        message_id = _text(row, "messageId") or _text(row, "eventId")
        if not message_id:
            return
        now_ms = _iso_to_ms(datetime.now(timezone.utc).isoformat())
        connection = _open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            _record_row(connection, row, assistant_agent_id, now_ms)
            connection.execute("COMMIT")
        finally:
            connection.close()
    except Exception as exc:
        _debug_logger.warning(
            f"Dispatch ledger record failed silently. error={type(exc).__name__}"
        )


def record_inbox_status_change(
    agent_id: str, message_ids: list[str] | tuple[str, ...], status: str
) -> None:
    """Mirror a JSONL status transition (consumed/revoked) into the ledger.

    Never raises; unknown ids are ignored (rows predating the ledger are
    repaired by harvest, which reads the JSONL status as truth).
    """

    try:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"consumed", "revoked"}:
            return
        ids = sorted({str(item or "").strip() for item in message_ids} - {""})
        if not ids:
            return
        now_ms = _iso_to_ms(datetime.now(timezone.utc).isoformat())
        connection = _open_writable()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for message_id in ids:
                connection.execute(
                    "UPDATE dispatches SET status=?, updated_at_ms=? WHERE message_id=?",
                    (normalized_status, now_ms, message_id),
                )
                connection.execute(
                    "UPDATE receipts SET status=?, updated_at_ms=? WHERE message_id=?",
                    (normalized_status, now_ms, message_id),
                )
            connection.execute("COMMIT")
        finally:
            connection.close()
    except Exception as exc:
        _debug_logger.warning(
            f"Dispatch ledger status mirror failed silently. error={type(exc).__name__}"
        )


# ---------------------------------------------------------------------------
# Harvest (change-driven backfill; JSONL rows are the truth)
# ---------------------------------------------------------------------------


def _harvest_inbox_rows(
    path: Path, *, cap: int
) -> tuple[list[dict[str, Any]], bool, Counter]:
    """Forward read of the newest ``cap`` rows, chronologically ordered.

    Returns ``(rows, complete, instance_counts)``. ``complete`` is False
    when any line failed to parse or the read was interrupted — a degraded
    harvest must never feed a uniqueness proof downstream. Line order is
    JSONL append order, so the rows come back oldest-first.
    """

    try:
        if not path.exists():
            return [], True, Counter()
        if path.stat().st_size > _HARVEST_MAX_FILE_BYTES:
            return [], False, Counter()
    except OSError:
        return [], False, Counter()
    rows: list[dict[str, Any]] = []
    complete = True
    line_count = 0
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line_count += 1
                if line_count > _HARVEST_MAX_LINES:
                    complete = False
                    break
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except (ValueError, RecursionError):
                    complete = False
                    continue
                if not isinstance(payload, dict):
                    complete = False
                    continue
                rows.append(payload)
    except OSError:
        complete = False
    instances = Counter(
        str(row.get("messageId") or row.get("eventId") or "").strip() for row in rows
    )
    instances.pop("", None)
    return rows[-cap:], complete, instances


def ensure_harvested(assistant_agent_id: str) -> bool:
    """Change-driven harvest of every agent inbox into the ledger.

    Returns True when the ledger is ready for reads. Idempotent: a matching
    signature snapshot short-circuits, and every upsert merges monotonic
    state, so a concurrent double harvest converges to the same rows.
    A changed PA identity wipes the ledger before re-harvesting.
    """

    from core.web.services import personal_assistant_dispatches_service as dispatches_service

    agent_rows = dispatches_service._agent_rows()
    try:
        connection = _open_writable()
    except Exception as exc:
        _debug_logger.warning(
            f"Dispatch ledger harvest unavailable. error={type(exc).__name__}"
        )
        return False
    try:
        marker = connection.execute(
            "SELECT pa_agent_id FROM ledger_meta WHERE singleton=1"
        ).fetchone()
        if not marker or not str(marker[0] or "").strip():
            # One-time integrity gate: the ledger becomes trusted for reads
            # only after a quick_check pass (per-message writes stay O(1)
            # afterwards).
            if list(connection.execute("PRAGMA quick_check")) != [("ok",)]:
                raise DispatchLedgerUnavailableError("dispatch_ledger_integrity_failed")
        if marker and str(marker[0] or "").strip() not in ("", assistant_agent_id):
            # The PA identity changed: previous rows are foreign. Wipe.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM dispatches")
            connection.execute("DELETE FROM receipts")
            connection.execute("DELETE FROM harvest_state")
            connection.execute(
                "UPDATE ledger_meta SET pa_agent_id='', backfill_at='' WHERE singleton=1"
            )
            connection.execute("COMMIT")
        signatures: dict[str, tuple[int, int] | None] = {}
        inbox_paths: dict[str, Path] = {}
        for agent_row in agent_rows:
            agent_id = dispatches_service._text(agent_row, "agentId")
            if not agent_id:
                continue
            inbox_path = dispatches_service._inbox_path(agent_row)
            inbox_paths[agent_id] = inbox_path
            try:
                stat = inbox_path.stat()
                signatures[agent_id] = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                # A missing inbox participates in signature comparison as a
                # zero row, so its first message flips the signature exactly
                # once instead of forcing a re-harvest on every read.
                signatures[agent_id] = (0, 0)
        stored = {
            str(row[0]): (int(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT agent_id, mtime_ns, size FROM harvest_state"
            )
        }
        if (
            marker
            and str(marker[0] or "").strip() == assistant_agent_id
            and stored
            and signatures == stored
        ):
            return True
        # Full bounded harvest (re-counting instances needs every inbox in
        # one pass, so any signature change re-reads all of them).
        harvested: list[tuple[str, dict[str, Any]]] = []
        completeness: dict[str, bool] = {}
        for agent_id, inbox_path in inbox_paths.items():
            cap = (
                _HARVEST_ASSISTANT_INBOX_CAP
                if agent_id == assistant_agent_id
                else _HARVEST_TARGET_INBOX_CAP
            )
            rows, complete, _counts = _harvest_inbox_rows(inbox_path, cap=cap)
            completeness[agent_id] = complete
            for row in rows:
                harvested.append((agent_id, row))
        # JSONL append order is chronological; replaying forward lets the
        # materialized task status converge to the latest report.
        now_ms = _iso_to_ms(datetime.now(timezone.utc).isoformat())
        connection.execute("BEGIN IMMEDIATE")
        try:
            live_agent_ids = [agent_id for agent_id in inbox_paths]
            for inbox_agent_id, row in harvested:
                _record_row(
                    connection, row, assistant_agent_id, now_ms,
                    inbox_agent_id=inbox_agent_id,
                )
            # Instance ledger: one row per JSONL row occurrence. The JSONL
            # window counts instances — a duplicated id occupies several
            # slots and only pairs while exactly one instance is visible —
            # so the read view derives its window and visibility counts
            # from this table instead of the deduplicated dispatches PK.
            connection.execute("DELETE FROM dispatch_instances")
            for inbox_agent_id, row in harvested:
                classification = _classify(row, assistant_agent_id)
                if classification not in (_DISPATCH_KIND, _FOLLOWUP_KIND_ROW):
                    continue
                message_id = _text(row, "messageId") or _text(row, "eventId")
                if not message_id:
                    continue
                connection.execute(
                    "INSERT INTO dispatch_instances("
                    "inbox_agent_id, message_id, sent_at_ms, sort_message_id) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        inbox_agent_id,
                        message_id,
                        _iso_to_ms(_text(row, "createdAt")),
                        message_id,
                    ),
                )
            # Rows whose owning inbox vanished (agent removed) leave the view.
            placeholders = ",".join("?" for _ in live_agent_ids) or "''"
            connection.execute(
                f"DELETE FROM dispatches WHERE inbox_agent_id NOT IN ({placeholders})",
                tuple(live_agent_ids),
            )
            connection.execute(
                f"DELETE FROM receipts WHERE inbox_agent_id NOT IN ({placeholders})",
                tuple(live_agent_ids),
            )
            connection.execute(
                f"DELETE FROM dispatch_instances WHERE inbox_agent_id NOT IN ({placeholders})",
                tuple(live_agent_ids),
            )
            connection.execute("DELETE FROM harvest_state")
            for agent_id, sig in signatures.items():
                connection.execute(
                    "INSERT INTO harvest_state(agent_id, mtime_ns, size, complete) "
                    "VALUES (?, ?, ?, ?)",
                    (agent_id, int(sig[0]), int(sig[1]), 1 if completeness.get(agent_id) else 0),
                )
            connection.execute(
                "UPDATE ledger_meta SET pa_agent_id=?, backfill_at=? WHERE singleton=1",
                (assistant_agent_id, datetime.now(timezone.utc).isoformat()),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        return True
    except Exception as exc:
        _debug_logger.warning(
            f"Dispatch ledger harvest failed silently. error={type(exc).__name__}"
        )
        return False
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Ledger-backed read view (projection shaped like the JSONL read model)
# ---------------------------------------------------------------------------

_DISPATCH_COLUMNS = (
    "message_id, row_kind, source_agent_id, target_agent_id, inbox_agent_id, "
    "target_session_id, source_session_id, thread_id, kind, summary, "
    "target_agent_name, status, sent_at, task_status, followup_round, "
    "followup_at, pa_followup_of_message_id"
)
_RECEIPT_COLUMNS = (
    "message_id, source_agent_id, target_agent_id, inbox_agent_id, "
    "target_session_id, source_session_id, thread_id, kind, summary, "
    "source_agent_name, status, reply_to_message_id, pa_followup_of_message_id, "
    "pa_followup_round, personal_assistant_task, received_at"
)


def _dispatch_row_dict(db_row: tuple) -> dict[str, Any]:
    (
        message_id, row_kind, source_agent_id, target_agent_id, inbox_agent_id,
        target_session_id, source_session_id, thread_id, kind, summary,
        target_agent_name, status, sent_at, _task_status, _followup_round,
        _followup_at, _pa_followup_of,
    ) = db_row
    return {
        "messageId": message_id,
        "eventId": message_id,
        "rowKind": row_kind,
        "sourceAgentId": source_agent_id,
        "targetAgentId": target_agent_id,
        "inboxAgentId": inbox_agent_id,
        "targetSessionId": target_session_id,
        "threadId": thread_id,
        "kind": kind,
        "summary": summary,
        "targetAgentName": target_agent_name,
        "status": status,
        "createdAt": sent_at,
        # The ledger stores the envelope keys as explicit columns; synthesize
        # the metadata shape the JSONL read-model helpers expect.
        "metadata": {"sourceSessionId": source_session_id},
    }


def _receipt_row_dict(db_row: tuple) -> dict[str, Any]:
    (
        message_id, source_agent_id, target_agent_id, inbox_agent_id,
        target_session_id, source_session_id, thread_id, kind, summary,
        source_agent_name, status, reply_to, pa_followup_of, pa_followup_round,
        task_json, received_at,
    ) = db_row
    task = _parse_task(task_json)
    metadata: dict[str, Any] = {
        "replyToMessageId": reply_to,
        "paFollowupOfMessageId": pa_followup_of,
        "paFollowupRound": pa_followup_round if type(pa_followup_round) is int else None,
        "sourceSessionId": source_session_id,
        "targetSessionId": target_session_id,
    }
    if task is not None:
        metadata["personalAssistantTask"] = task
    return {
        "messageId": message_id,
        "eventId": message_id,
        "sourceAgentId": source_agent_id,
        "targetAgentId": target_agent_id,
        "inboxAgentId": inbox_agent_id,
        "targetSessionId": target_session_id,
        "threadId": thread_id,
        "kind": kind,
        "summary": summary,
        "sourceAgentName": source_agent_name,
        "status": status,
        "createdAt": received_at,
        "metadata": metadata,
    }


def _unique_thread_dispatch_id(
    connection: sqlite3.Connection, *, thread_id: str, target_agent_id: str
) -> str | None:
    """Authoritative thread uniqueness over ledger history.

    Only dispatch rows living in their own target agent's inbox count,
    deduplicated by id (the JSONL thread predicate dedupes the same way);
    duplicate visibility is handled by the instance-count check at pairing.
    """

    rows = connection.execute(
        "SELECT DISTINCT message_id FROM dispatches "
        "WHERE row_kind='dispatch' AND target_agent_id=? AND thread_id=? "
        "AND inbox_agent_id=?",
        (target_agent_id, thread_id, target_agent_id),
    ).fetchall()
    ids = {str(row[0]) for row in rows if str(row[0]).strip()}
    return next(iter(ids)) if len(ids) == 1 else None


# Signature memo for panel reads: the file stat (mtime_ns, size) is the
# invalidation key, mirroring the JSONL recent-cache pattern in
# agent_directory. Panel(5s)+attention(10s)+patrol(60s) all read; the memo
# keeps steady-state polls off SQLite.
_VIEW_CACHE: dict[tuple, dict[str, Any]] = {}
_VIEW_CACHE_LOCK = threading.Lock()
_VIEW_CACHE_LIMIT = 4


def _ledger_file_signature() -> tuple[int, int] | None:
    try:
        stat = ledger_database_path().stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def read_dispatch_view_cached(
    assistant_agent_id: str,
    *,
    window: int,
    receipt_window: int,
) -> dict[str, Any] | None:
    """``read_dispatch_view`` behind a signature memo; never raises."""

    signature = _ledger_file_signature()
    cache_key = (
        (signature, int(window), int(receipt_window)) if signature is not None else None
    )
    if cache_key is not None:
        with _VIEW_CACHE_LOCK:
            cached = _VIEW_CACHE.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)
    view = read_dispatch_view(
        assistant_agent_id, window=window, receipt_window=receipt_window
    )
    if view is not None and cache_key is not None:
        with _VIEW_CACHE_LOCK:
            if len(_VIEW_CACHE) >= _VIEW_CACHE_LIMIT:
                _VIEW_CACHE.clear()
            _VIEW_CACHE[cache_key] = copy.deepcopy(view)
    return copy.deepcopy(view) if view is not None else None


def read_dispatch_view(
    assistant_agent_id: str,
    *,
    window: int,
    receipt_window: int,
) -> dict[str, Any] | None:
    """Project the ledger into the JSONL read model's response shape.

    Returns None when the ledger holds no dispatch rows (the caller then
    falls back to the legacy JSONL scan). Late visibility: receipts are
    paired to visible dispatches without a receipt-window limit, so
    out-of-window receipts still attach and terminal task reports never
    regress to ``running``.
    """

    from core.web.services import personal_assistant_dispatches_service as helpers

    connection = _open_readable()
    try:
        # The JSONL window counts instances: dispatch_rows is the newest
        # ``window`` matching JSONL rows (a duplicated id occupies several
        # slots and appears once per instance). Mirror that over the
        # instance ledger.
        instance_rows = list(
            connection.execute(
                "SELECT inbox_agent_id, message_id, sent_at_ms, sort_message_id "
                "FROM dispatch_instances ORDER BY sent_at_ms DESC, "
                "sort_message_id DESC LIMIT ?",
                (int(window),),
            )
        )
        visible_ids = {str(row[1]) for row in instance_rows}
        if not visible_ids:
            return None
        dispatch_db_rows = list(
            connection.execute(
                f"SELECT {_DISPATCH_COLUMNS} FROM dispatches "
                f"WHERE row_kind='dispatch' AND message_id IN "
                f"({','.join('?' for _ in visible_ids)})",
                tuple(visible_ids),
            )
        )
        visible_by_id = {}
        for db_row in dispatch_db_rows:
            row_dict = _dispatch_row_dict(db_row)
            visible_by_id[row_dict["messageId"]] = row_dict
        # Only dispatch-kind ids are pairable targets; followup instances in
        # the window occupy slots but never resolve as reply targets (the
        # JSONL path excludes them from dispatch_rows the same way).
        visible_ids = set(visible_by_id)
        # Response order/presence follow the instance window; a duplicated
        # id renders once per visible instance, exactly like the JSONL path.
        visible_instances: list[dict[str, Any]] = []
        instance_counts: Counter = Counter()
        for _inbox, message_id, _sent_ms, _sort in instance_rows:
            dispatch_row = visible_by_id.get(str(message_id))
            if dispatch_row is None:
                continue
            instance_counts[str(message_id)] += 1
            visible_instances.append(dispatch_row)

        # Uniqueness proofs (thread match, chase resolution) must come from
        # complete harvests only — same defensive rule as the JSONL strict
        # scans that raise on a partial read.
        complete_inboxes = {
            str(row[0])
            for row in connection.execute(
                "SELECT agent_id FROM harvest_state WHERE complete=1"
            )
        }

        # Chase map: a reply addressed to a follow-up row resolves to the
        # chased origin dispatch, under the JSONL path's authority rules —
        # the chase must live in its own target's inbox, be unduplicated,
        # and share the origin's thread.
        followup_origin: dict[str, dict[str, str]] = {}
        placeholders = ",".join("?" for _ in visible_ids)
        for (
            chase_id, origin_id, chase_target, chase_inbox, chase_thread,
        ) in connection.execute(
            "SELECT message_id, pa_followup_of_message_id, target_agent_id, "
            "inbox_agent_id, thread_id FROM dispatches "
            f"WHERE row_kind='followup' AND pa_followup_of_message_id IN ({placeholders})",
            tuple(visible_ids),
        ):
            # The JSONL strict scan proves the chase unique inside its own
            # authoritative inbox; a duplicated row (or a foreign copy) or
            # an incomplete harvest voids that proof.
            inbox_instances = connection.execute(
                "SELECT COUNT(*) FROM dispatch_instances "
                "WHERE message_id=? AND inbox_agent_id=?",
                (str(chase_id), str(chase_inbox)),
            ).fetchone()[0]
            if (
                str(chase_inbox) == str(chase_target)
                and int(inbox_instances) == 1
                and str(chase_inbox) in complete_inboxes
            ):
                followup_origin[str(chase_id)] = {
                    "origin": str(origin_id),
                    "target": str(chase_target),
                    "thread": str(chase_thread),
                }

        # Tier A - explicit pairing without a receipt-window limit (late
        # visibility). Candidate receipts reply either to a visible dispatch
        # or to a chase rooted in one.
        explicit_targets = sorted(visible_ids | set(followup_origin))
        explicit_placeholders = ",".join("?" for _ in explicit_targets)
        tier_a_rows = list(
            connection.execute(
                f"SELECT {_RECEIPT_COLUMNS} FROM receipts "
                f"WHERE reply_to_message_id IN ({explicit_placeholders}) "
                "ORDER BY received_at_ms ASC, message_id ASC",
                tuple(explicit_targets),
            )
        )

        # Tier B - the legacy receipt window (thread-matching parity plus the
        # unmatchedReceipts population).
        tier_b_rows = list(
            connection.execute(
                f"SELECT {_RECEIPT_COLUMNS} FROM receipts "
                "ORDER BY received_at_ms DESC, message_id DESC LIMIT ?",
                (int(receipt_window),),
            )
        )

        def _origin_dispatch_id(candidate: dict[str, Any]) -> str:
            reply_to = helpers._text(helpers._metadata(candidate), "replyToMessageId")
            if not reply_to:
                return ""
            if reply_to in visible_ids:
                return reply_to
            chase = followup_origin.get(reply_to)
            if chase is None or chase["origin"] not in visible_ids:
                return ""
            origin = visible_by_id[chase["origin"]]
            if (
                chase["target"] == helpers._text(origin, "targetAgentId")
                and chase["thread"] == helpers._text(origin, "threadId")
            ):
                return chase["origin"]
            return ""

        receipts_by_dispatch: dict[str, list[dict[str, Any]]] = {}
        unmatched: list[dict[str, Any]] = []
        seen_receipt_ids: set[str] = set()
        tier_b_ids = {row[0] for row in tier_b_rows}

        for db_row in tier_a_rows + tier_b_rows:
            candidate = _receipt_row_dict(db_row)
            message_id = candidate["messageId"]
            if message_id in seen_receipt_ids:
                continue
            seen_receipt_ids.add(message_id)
            receipt = helpers._receipt_row(candidate)
            source_agent_id = helpers._text(candidate, "sourceAgentId")
            target_dispatch: dict[str, Any] | None = None
            origin_id = _origin_dispatch_id(candidate)
            if origin_id:
                origin = visible_by_id.get(origin_id)
                if (
                    origin is not None
                    and instance_counts.get(origin_id, 0) == 1
                    and source_agent_id
                    and source_agent_id == helpers._text(origin, "targetAgentId")
                ):
                    target_dispatch = origin
            elif (
                helpers._text(candidate, "threadId")
                and source_agent_id
                and message_id in tier_b_ids
                and source_agent_id in complete_inboxes
            ):
                # Thread matching mirrors the JSONL path: one unique
                # same-thread same-source dispatch across authoritative
                # ledger history, paired only when visible in the current
                # window and present there exactly once.
                unique_id = _unique_thread_dispatch_id(
                    connection,
                    thread_id=helpers._text(candidate, "threadId"),
                    target_agent_id=source_agent_id,
                )
                if unique_id and instance_counts.get(unique_id, 0) == 1:
                    target_dispatch = visible_by_id.get(unique_id)
            if target_dispatch is not None:
                receipt.update(helpers._task_report(candidate, target_dispatch))
                receipts_by_dispatch.setdefault(target_dispatch["messageId"], []).append(
                    receipt
                )
            elif message_id in tier_b_ids:
                unmatched.append(receipt)

        dispatches: list[dict[str, Any]] = []
        for dispatch_row in visible_instances:
            message_id = dispatch_row["messageId"]
            matched = receipts_by_dispatch.get(message_id) or []
            matched.sort(key=lambda item: (item["receivedAt"], item["messageId"]))
            dispatches.append(
                {
                    "messageId": message_id,
                    "threadId": helpers._text(dispatch_row, "threadId") or None,
                    "targetAgentId": helpers._text(dispatch_row, "targetAgentId"),
                    "targetAgentName": helpers._text(dispatch_row, "targetAgentName"),
                    "targetSessionId": helpers._text(dispatch_row, "targetSessionId"),
                    "sourceSessionId": helpers._text(
                        helpers._metadata(dispatch_row), "sourceSessionId"
                    ),
                    "summary": helpers._text(dispatch_row, "summary"),
                    "deliveryStatus": helpers._status(dispatch_row),
                    "taskStatus": helpers._dispatch_task_status(
                        helpers._status(dispatch_row), matched
                    ),
                    "sentAt": helpers._text(dispatch_row, "createdAt"),
                    "receipts": matched,
                }
            )
        unmatched.sort(
            key=lambda item: (item["receivedAt"], item["messageId"]), reverse=True
        )
        return {
            "dispatches": dispatches,
            "unmatchedReceipts": unmatched,
        }
    finally:
        connection.close()
