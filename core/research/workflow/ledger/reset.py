"""Governed, reversible reset port for one team's workflow-ledger records.

The caller never receives a SQLite connection or a filesystem path.  This
module runs through :class:`WorkflowLedgerStore`'s single writer and captures
only the rows belonging to an explicitly named team.  A staged snapshot is
kept until the enclosing reset either compensates or finalizes it.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from .store import WorkflowLedgerStore


LEDGER_RESET_PORT_KIND = "workflow_ledger_team_reset"
LEDGER_RESET_PORT_SCHEMA_VERSION = 1


class WorkflowLedgerResetError(RuntimeError):
    """Raised when the ledger reset cannot prove or preserve its boundary."""


_LOCK = threading.RLock()
_STAGES: dict[str, dict[str, Any]] = {}

# Parent/child order is important for SQLite's immediate foreign-key checks.
_DELETE_TABLES = (
    "handoff_receipts",
    "human_tasks",
    "recovery_records",
    "projection_cursors",
    "artifact_receipts",
    "budget_receipts",
    "execution_anchors",
    "outbox_actions",
    "workflow_events",
    "handoffs",
    "node_attempts",
    "workflow_commands",
    "workflow_runs",
    "catalog_run_authorizations",
)
_RESTORE_TABLES = tuple(reversed(_DELETE_TABLES))


def _text(value: Any, *, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise WorkflowLedgerResetError(f"{field} is required")
    return result


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _table_columns(connection: Any, table: str) -> list[str]:
    rows = list(connection.execute(f"PRAGMA table_info({table})"))
    return [str(row[1]) for row in rows]


def _rows(connection: Any, table: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    columns = _table_columns(connection, table)
    if not columns:
        return []
    return [dict(zip(columns, row, strict=True)) for row in connection.execute(sql, params)]


def _in_clause(values: list[str]) -> tuple[str, tuple[str, ...]]:
    if not values:
        return "(NULL)", ()
    return "(" + ",".join("?" for _ in values) + ")", tuple(values)


def _snapshot(connection: Any, team_id: str) -> dict[str, list[dict[str, Any]]]:
    runs = _rows(
        connection,
        "workflow_runs",
        "SELECT * FROM workflow_runs WHERE team_id = ? ORDER BY run_id",
        (team_id,),
    )
    run_ids = [str(row["run_id"]) for row in runs]
    run_in, run_params = _in_clause(run_ids)
    attempts = _rows(
        connection,
        "node_attempts",
        f"SELECT * FROM node_attempts WHERE run_id IN {run_in} ORDER BY node_run_id",
        run_params,
    )
    attempt_ids = [str(row["node_run_id"]) for row in attempts]
    attempt_in, attempt_params = _in_clause(attempt_ids)
    handoffs = _rows(
        connection,
        "handoffs",
        f"SELECT * FROM handoffs WHERE run_id IN {run_in} ORDER BY handoff_id",
        run_params,
    )
    handoff_ids = [str(row["handoff_id"]) for row in handoffs]
    handoff_in, handoff_params = _in_clause(handoff_ids)

    return {
        "catalog_run_authorizations": _rows(
            connection,
            "catalog_run_authorizations",
            "SELECT * FROM catalog_run_authorizations WHERE team_id = ? ORDER BY authorization_id",
            (team_id,),
        ),
        "workflow_runs": runs,
        "workflow_commands": _rows(connection, "workflow_commands", f"SELECT * FROM workflow_commands WHERE run_id IN {run_in} ORDER BY command_id", run_params),
        "node_attempts": attempts,
        "workflow_events": _rows(connection, "workflow_events", f"SELECT * FROM workflow_events WHERE run_id IN {run_in} ORDER BY run_id, sequence", run_params),
        "outbox_actions": _rows(connection, "outbox_actions", f"SELECT * FROM outbox_actions WHERE run_id IN {run_in} ORDER BY action_id", run_params),
        "execution_anchors": _rows(connection, "execution_anchors", f"SELECT * FROM execution_anchors WHERE node_run_id IN {attempt_in} ORDER BY anchor_id", attempt_params),
        "artifact_receipts": _rows(connection, "artifact_receipts", f"SELECT * FROM artifact_receipts WHERE run_id IN {run_in} ORDER BY receipt_id", run_params),
        "budget_receipts": _rows(connection, "budget_receipts", f"SELECT * FROM budget_receipts WHERE run_id IN {run_in} ORDER BY receipt_id", run_params),
        "handoffs": handoffs,
        "handoff_receipts": _rows(connection, "handoff_receipts", f"SELECT * FROM handoff_receipts WHERE handoff_id IN {handoff_in} ORDER BY handoff_id, ordinal", handoff_params),
        "human_tasks": _rows(connection, "human_tasks", f"SELECT * FROM human_tasks WHERE run_id IN {run_in} ORDER BY task_id", run_params),
        "recovery_records": _rows(connection, "recovery_records", f"SELECT * FROM recovery_records WHERE run_id IN {run_in} ORDER BY recovery_id", run_params),
        "projection_cursors": _rows(connection, "projection_cursors", f"SELECT * FROM projection_cursors WHERE run_id IN {run_in} ORDER BY projection_name, run_id", run_params),
    }


def _summary(stage: Mapping[str, Any]) -> dict[str, Any]:
    rows = stage.get("rows") if isinstance(stage.get("rows"), Mapping) else {}
    return {
        "schemaVersion": LEDGER_RESET_PORT_SCHEMA_VERSION,
        "kind": LEDGER_RESET_PORT_KIND,
        "stageId": str(stage["stageId"]),
        "resetId": str(stage["resetId"]),
        "teamId": str(stage["teamId"]),
        "status": str(stage.get("status") or "staged"),
        "runCount": len(rows.get("workflow_runs") or []),
        "recordCount": sum(len(value) for value in rows.values() if isinstance(value, list)),
        "fingerprint": str(stage["fingerprint"]),
    }


def _stage(stage: Mapping[str, Any], *, reset_id: str | None = None) -> dict[str, Any]:
    if not isinstance(stage, Mapping):
        raise WorkflowLedgerResetError("ledger stage must be an object")
    if stage.get("schemaVersion") != LEDGER_RESET_PORT_SCHEMA_VERSION or stage.get("kind") != LEDGER_RESET_PORT_KIND:
        raise WorkflowLedgerResetError("ledger stage schema is invalid")
    stage_id = _text(stage.get("stageId"), field="stageId")
    with _LOCK:
        cached = _STAGES.get(stage_id)
    if cached is None:
        raise WorkflowLedgerResetError("ledger stage is unavailable")
    for key in ("resetId", "teamId", "fingerprint"):
        if str(stage.get(key) or "") != str(cached.get(key) or ""):
            raise WorkflowLedgerResetError(f"ledger stage {key} does not match")
    if reset_id is not None and str(reset_id).strip() != str(cached["resetId"]):
        raise WorkflowLedgerResetError("ledger stage resetId does not match")
    return cached


def prepare_team_ledger_reset_stage(
    store: WorkflowLedgerStore,
    team_id: str,
    reset_id: str,
) -> dict[str, Any]:
    """Capture an exact team-scoped snapshot through the ledger read facade."""

    team = _text(team_id, field="teamId")
    reset = _text(reset_id, field="resetId")
    rows = store.read(lambda repo: _snapshot(repo.connection, team))
    stage = {
        "stageId": f"ledger-stage-{uuid4().hex}",
        "resetId": reset,
        "teamId": team,
        "rows": rows,
        "fingerprint": _json_hash(rows),
        "status": "staged",
    }
    with _LOCK:
        _STAGES[str(stage["stageId"])] = stage
    return _summary(stage)


def _delete_snapshot(connection: Any, rows: Mapping[str, list[dict[str, Any]]]) -> int:
    connection.execute("PRAGMA defer_foreign_keys = ON")
    changed = 0
    for table in _DELETE_TABLES:
        table_rows = rows.get(table) or []
        if not table_rows:
            continue
        columns = _table_columns(connection, table)
        primary = {
            "catalog_run_authorizations": ("authorization_id",),
            "workflow_runs": ("run_id",),
            "workflow_commands": ("command_id",),
            "node_attempts": ("node_run_id",),
            "workflow_events": ("run_id", "sequence"),
            "outbox_actions": ("action_id",),
            "execution_anchors": ("anchor_id",),
            "artifact_receipts": ("receipt_id",),
            "budget_receipts": ("receipt_id",),
            "handoffs": ("handoff_id",),
            "handoff_receipts": ("handoff_id", "receipt_id"),
            "human_tasks": ("task_id",),
            "recovery_records": ("recovery_id",),
            "projection_cursors": ("projection_name", "run_id"),
        }[table]
        if any(key not in columns for key in primary):
            raise WorkflowLedgerResetError(f"ledger table {table} schema is unsupported")
        for row in table_rows:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE " + " AND ".join(f"{key} = ?" for key in primary),
                tuple(row[key] for key in primary),
            )
            # sqlite3 exposes ``cursor.rowcount`` while APSW exposes the
            # connection-level change counter.  The ledger supports both
            # implementations, so an APSW delete must not be reported as a
            # no-op merely because its cursor lacks rowcount.
            rowcount = getattr(cursor, "rowcount", None)
            if rowcount in (None, -1, 0):
                changes = getattr(connection, "changes", None)
                rowcount = changes() if callable(changes) else rowcount
            changed += max(0, int(rowcount or 0))
    return changed


def purge_team_ledger_reset_stage(
    store: WorkflowLedgerStore,
    stage: Mapping[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Remove only the exact staged records through the ledger writer."""

    cached = _stage(stage, reset_id=reset_id)
    if cached.get("status") == "destroyed":
        raise WorkflowLedgerResetError("finalized ledger stage cannot be purged")
    team = str(cached["teamId"])
    rows = cached["rows"]

    def mutate(uow: Any) -> int:
        current = _snapshot(uow.connection, team)
        if _json_hash(current) != str(cached["fingerprint"]):
            raise WorkflowLedgerResetError("ledger changed after reset staging")
        return _delete_snapshot(uow.connection, rows)

    changed = int(store.submit(mutate, force_flush=True).result())
    with _LOCK:
        cached["status"] = "purged"
    return {**_summary(cached), "operation": "purge", "changedRows": changed}


def restore_team_ledger_reset_stage(
    store: WorkflowLedgerStore,
    stage: Mapping[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Compensate a later reset-port failure by restoring the staged rows."""

    cached = _stage(stage, reset_id=reset_id)
    if cached.get("status") == "destroyed":
        raise WorkflowLedgerResetError("finalized ledger stage cannot be restored")
    team = str(cached["teamId"])
    rows = cached["rows"]

    def mutate(uow: Any) -> int:
        current = _snapshot(uow.connection, team)
        if any(current.values()):
            if _json_hash(current) == str(cached["fingerprint"]):
                return 0
            raise WorkflowLedgerResetError("ledger reset restore conflicts with current team records")
        uow.connection.execute("PRAGMA defer_foreign_keys = ON")
        restored = 0
        for table in _RESTORE_TABLES:
            for row in rows.get(table) or []:
                columns = list(row)
                uow.connection.execute(
                    f"INSERT INTO {table} (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
                    tuple(row[column] for column in columns),
                )
                restored += 1
        return restored

    changed = int(store.submit(mutate, force_flush=True).result())
    with _LOCK:
        cached["status"] = "restored"
    return {**_summary(cached), "operation": "restore", "changedRows": changed}


def destroy_team_ledger_reset_stage(
    stage: Mapping[str, Any],
    *,
    reset_id: str | None = None,
) -> dict[str, Any]:
    """Drop the in-memory recovery payload after the whole reset succeeds."""

    cached = _stage(stage, reset_id=reset_id)
    if cached.get("status") not in {"purged", "destroyed"}:
        raise WorkflowLedgerResetError("only a purged ledger stage can be finalized")
    with _LOCK:
        cached["status"] = "destroyed"
        cached["rows"] = {}
    return _summary(cached)


__all__ = [
    "LEDGER_RESET_PORT_KIND",
    "LEDGER_RESET_PORT_SCHEMA_VERSION",
    "WorkflowLedgerResetError",
    "destroy_team_ledger_reset_stage",
    "prepare_team_ledger_reset_stage",
    "purge_team_ledger_reset_stage",
    "restore_team_ledger_reset_stage",
]
