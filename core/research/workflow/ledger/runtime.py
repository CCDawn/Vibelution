"""APSW runtime adapter and safe SQLite version guard for the Workflow Ledger.

A small independent implementation (no imports from core/chat/conversation_store)
so research storage can never drag chat repository semantics into the ledger.
"""

from __future__ import annotations

import apsw

SQLITE_SAFE_BACKPORTS = {(3, 44, 6), (3, 50, 7)}
SQLITE_FIRST_FULLY_FIXED_VERSION = (3, 51, 3)


class LedgerSqliteVersionError(RuntimeError):
    """The SQLite runtime is not safe for WAL storage."""


def sqlite_version_info() -> tuple[int, int, int]:
    raw = apsw.sqlitelibversion()
    return tuple(int(part) for part in raw.split("."))[:3]


def assess_sqlite_wal_runtime(version: tuple[int, int, int] | None = None) -> tuple[bool, str]:
    """WAL-reset race advisory: safe only on patched backports or >= 3.51.3."""
    normalized = version or sqlite_version_info()
    if normalized in SQLITE_SAFE_BACKPORTS or normalized >= SQLITE_FIRST_FULLY_FIXED_VERSION:
        return True, "safe"
    return False, "wal_reset_race"


def require_safe_sqlite_runtime() -> None:
    safe, code = assess_sqlite_wal_runtime()
    if not safe:
        raise LedgerSqliteVersionError(
            "Workflow Ledger WAL storage requires SQLite 3.51.3 or a patched "
            f"3.44.6/3.50.7 backport; detected {code} on {apsw.sqlitelibversion()}"
        )


def open_ledger_connection(path: str, *, read_only: bool = False) -> apsw.Connection:
    """Open a ledger connection with the fixed pragma policy (spec 6.1)."""
    from .errors import WorkflowLedgerCorruptionError

    try:
        if read_only:
            connection = apsw.Connection(path, flags=apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI)
        else:
            connection = apsw.Connection(
                path, flags=apsw.SQLITE_OPEN_READWRITE | apsw.SQLITE_OPEN_CREATE
            )
        connection.setbusytimeout(5000)
        if not read_only:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA temp_store = MEMORY")
        else:
            connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except apsw.CorruptError as exc:
        raise WorkflowLedgerCorruptionError(f"ledger database image is malformed: {exc}") from exc
