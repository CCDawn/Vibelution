from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_KEEP_LATEST = 50
MAX_KEEP_LATEST = 500


def normalize_keep_latest(value: int | None) -> int:
    if value is None:
        return DEFAULT_KEEP_LATEST
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_KEEP_LATEST
    return max(1, min(parsed, MAX_KEEP_LATEST))


def build_git_memory_maintenance_report(
    db_path: str | Path,
    *,
    keep_latest: int | None = None,
    integrity_check: bool = False,
    executable: str | Path | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Return a Git memory maintenance report, preferring the Rust accelerator when available."""

    normalized_db_path = Path(db_path)
    normalized_keep_latest = normalize_keep_latest(keep_latest)
    binary_path = Path(executable) if executable else default_maintenance_binary()
    if not binary_path or not binary_path.exists():
        fallback = build_python_git_memory_maintenance_report(
            normalized_db_path,
            keep_latest=normalized_keep_latest,
            integrity_check=integrity_check,
        )
        fallback["accelerator"] = {
            "available": False,
            "reason": "rust_binary_missing",
            "path": str(binary_path) if binary_path else "",
        }
        return fallback

    command = [
        str(binary_path),
        "git-memory",
        "--db",
        str(normalized_db_path),
        "--keep-latest",
        str(normalized_keep_latest),
    ]
    if integrity_check:
        command.append("--integrity-check")
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        fallback = build_python_git_memory_maintenance_report(
            normalized_db_path,
            keep_latest=normalized_keep_latest,
            integrity_check=integrity_check,
        )
        fallback["accelerator"] = {
            "available": False,
            "reason": "rust_binary_failed",
            "returnCode": completed.returncode,
            "stderrTail": _tail(completed.stderr),
        }
        return fallback
    payload = json.loads(completed.stdout)
    if isinstance(payload, dict):
        payload["accelerator"] = {
            "available": True,
            "path": str(binary_path),
        }
    return payload


def default_maintenance_binary() -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    crate_root = Path(__file__).resolve().parents[2] / "crates" / "vibelution-maintenance"
    release_binary = crate_root / "target" / "release" / f"vibelution-maintenance{suffix}"
    if release_binary.exists():
        return release_binary
    return crate_root / "target" / "debug" / f"vibelution-maintenance{suffix}"


def build_python_git_memory_maintenance_report(
    db_path: str | Path,
    *,
    keep_latest: int | None = None,
    integrity_check: bool = False,
) -> dict[str, Any]:
    normalized_db_path = Path(db_path)
    normalized_keep_latest = normalize_keep_latest(keep_latest)
    with sqlite3.connect(f"file:{normalized_db_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0] if integrity_check else "skipped"
        report = {
            "ok": True,
            "schemaVersion": 1,
            "tool": "vibelution-maintenance",
            "command": "git-memory",
            "dbPath": str(normalized_db_path),
            "keepLatest": normalized_keep_latest,
            "integrityCheckMode": "full" if integrity_check else "skipped",
            "integrityCheck": integrity,
            "tables": {
                "gitWorkingTreeSnapshot": _table_stats(
                    conn,
                    "GitWorkingTreeSnapshot",
                    "snapshot_id LIKE 'wt-%'",
                ),
                "gitFileChange": _table_stats(conn, "GitFileChange", "is_worktree = 1"),
                "gitEntityChange": _table_stats(conn, "GitEntityChange", "is_worktree = 1"),
            },
            "pruneDryRun": _prune_dry_run(conn, normalized_keep_latest),
            "elapsedMs": 0,
        }
    return report


def _table_stats(conn: sqlite3.Connection, table: str, worktree_where: str) -> dict[str, Any]:
    if not _table_exists(conn, table):
        return {"exists": False, "rowCount": 0, "worktreeRows": 0}
    return {
        "exists": True,
        "rowCount": _count(conn, f"SELECT COUNT(*) FROM {table}"),
        "worktreeRows": _count(conn, f"SELECT COUNT(*) FROM {table} WHERE {worktree_where}"),
    }


def _prune_dry_run(conn: sqlite3.Connection, keep_latest: int) -> dict[str, Any]:
    if not _table_exists(conn, "GitWorkingTreeSnapshot"):
        return {
            "candidateSnapshots": 0,
            "candidateFileRows": 0,
            "candidateEntityRows": 0,
            "sampleSnapshotIds": [],
        }
    prune_cte = """
        WITH prune AS (
            SELECT snapshot_id
            FROM GitWorkingTreeSnapshot
            WHERE snapshot_id LIKE 'wt-%'
            ORDER BY created_at DESC, snapshot_id DESC
            LIMIT -1 OFFSET ?
        )
    """
    candidate_snapshots = _count(conn, f"{prune_cte} SELECT COUNT(*) FROM prune", (keep_latest,))
    candidate_file_rows = 0
    if _table_exists(conn, "GitFileChange"):
        candidate_file_rows = _count(
            conn,
            f"""{prune_cte}
            SELECT COUNT(*)
            FROM GitFileChange
            WHERE is_worktree = 1
              AND commit_sha IN (SELECT snapshot_id FROM prune)
            """,
            (keep_latest,),
        )
    candidate_entity_rows = 0
    if _table_exists(conn, "GitEntityChange"):
        candidate_entity_rows = _count(
            conn,
            f"""{prune_cte}
            SELECT COUNT(*)
            FROM GitEntityChange
            WHERE is_worktree = 1
              AND commit_sha IN (SELECT snapshot_id FROM prune)
            """,
            (keep_latest,),
        )
    sample_snapshot_ids = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT snapshot_id
            FROM GitWorkingTreeSnapshot
            WHERE snapshot_id LIKE 'wt-%'
            ORDER BY created_at DESC, snapshot_id DESC
            LIMIT 5 OFFSET ?
            """,
            (keep_latest,),
        ).fetchall()
    ]
    return {
        "candidateSnapshots": candidate_snapshots,
        "candidateFileRows": candidate_file_rows,
        "candidateEntityRows": candidate_entity_rows,
        "sampleSnapshotIds": sample_snapshot_ids,
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row and int(row[0]) > 0)


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def _tail(value: str, *, max_chars: int = 2000) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[-max_chars:]
