# -*- coding: utf-8 -*-
"""Prune local Codex session JSONL files by timestamp.

The script is intentionally conservative:
- dry-run by default;
- backs up the original file before replacement;
- archives pruned lines as gzip JSONL;
- keeps session_meta lines so Codex can still identify the session.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_RETENTION_HOURS = 72


@dataclass
class PruneStats:
    path: Path
    original_bytes: int
    kept_bytes: int
    archived_bytes: int
    total_lines: int
    kept_lines: int
    archived_lines: int
    malformed_lines: int
    changed: bool
    backup_path: Path | None = None
    archive_path: Path | None = None
    error: str | None = None


@dataclass
class LogPruneStats:
    path: Path
    original_bytes: int
    wal_bytes: int
    shm_bytes: int
    total_rows: int
    old_rows: int
    kept_rows: int
    old_estimated_bytes: int
    kept_estimated_bytes: int
    changed: bool
    backup_paths: list[Path]


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def should_keep_record(record: object, cutoff: datetime) -> bool:
    if not isinstance(record, dict):
        return True
    if record.get("type") == "session_meta":
        return True
    timestamp = parse_timestamp(record.get("timestamp"))
    if timestamp is None:
        return True
    return timestamp >= cutoff


def iter_jsonl_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            yield line


def build_output_paths(path: Path, backup_root: Path, codex_home: Path) -> tuple[Path, Path]:
    try:
        relative = path.relative_to(codex_home)
    except ValueError:
        relative = Path(path.name)
    backup_path = backup_root / "originals" / relative
    archive_path = backup_root / "archived_lines" / relative.with_suffix(relative.suffix + ".gz")
    return backup_path, archive_path


def prune_session_file(
    path: Path,
    *,
    cutoff: datetime,
    backup_root: Path,
    codex_home: Path,
    apply: bool,
) -> PruneStats:
    original_bytes = path.stat().st_size
    backup_path, archive_path = build_output_paths(path, backup_root, codex_home)

    kept_lines: list[str] = []
    archived_lines: list[str] = []
    malformed_lines = 0
    total_lines = 0

    for line in iter_jsonl_lines(path):
        total_lines += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            kept_lines.append(line)
            continue
        if should_keep_record(record, cutoff):
            kept_lines.append(line)
        else:
            archived_lines.append(line)

    kept_text = "".join(kept_lines)
    archived_text = "".join(archived_lines)
    kept_bytes = len(kept_text.encode("utf-8"))
    archived_bytes = len(archived_text.encode("utf-8"))
    changed = bool(archived_lines)

    if apply and changed:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, backup_path)
            with gzip.open(archive_path, "wt", encoding="utf-8", newline="") as handle:
                handle.write(archived_text)
            fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(kept_text)
                os.replace(tmp_path, path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        except OSError as exc:
            return PruneStats(
                path=path,
                original_bytes=original_bytes,
                kept_bytes=kept_bytes,
                archived_bytes=archived_bytes,
                total_lines=total_lines,
                kept_lines=len(kept_lines),
                archived_lines=len(archived_lines),
                malformed_lines=malformed_lines,
                changed=changed,
                backup_path=backup_path if backup_path.exists() else None,
                archive_path=archive_path if archive_path.exists() else None,
                error=f"{type(exc).__name__}: {exc}",
            )

    return PruneStats(
        path=path,
        original_bytes=original_bytes,
        kept_bytes=kept_bytes,
        archived_bytes=archived_bytes,
        total_lines=total_lines,
        kept_lines=len(kept_lines),
        archived_lines=len(archived_lines),
        malformed_lines=malformed_lines,
        changed=changed,
        backup_path=backup_path if apply and changed else None,
        archive_path=archive_path if apply and changed else None,
    )


def discover_session_files(session_roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in session_roots:
        if root.is_file() and root.suffix == ".jsonl":
            files.append(root)
            continue
        if not root.exists():
            continue
        files.extend(path for path in root.rglob("*.jsonl") if path.is_file())
    return sorted(set(files))


def write_report(report_path: Path, stats: list[PruneStats], *, cutoff: datetime, apply: bool) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "apply" if apply else "dry-run",
        "cutoff": cutoff.isoformat(),
        "files": [
            {
                "path": str(item.path),
                "originalBytes": item.original_bytes,
                "keptBytes": item.kept_bytes,
                "archivedBytes": item.archived_bytes,
                "totalLines": item.total_lines,
                "keptLines": item.kept_lines,
                "archivedLines": item.archived_lines,
                "malformedLines": item.malformed_lines,
                "changed": item.changed,
                "backupPath": str(item.backup_path) if item.backup_path else None,
                "archivePath": str(item.archive_path) if item.archive_path else None,
            }
            for item in stats
        ],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sqlite_sidecar_paths(path: Path) -> list[Path]:
    return [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]


def copy_sqlite_backups(path: Path, backup_root: Path, codex_home: Path) -> list[Path]:
    copied: list[Path] = []
    for source in sqlite_sidecar_paths(path):
        if not source.exists():
            continue
        try:
            relative = source.relative_to(codex_home)
        except ValueError:
            relative = Path(source.name)
        destination = backup_root / "sqlite_originals" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)
    return copied


def inspect_logs_db(path: Path, cutoff_epoch: int) -> LogPruneStats | None:
    if not path.exists():
        return None
    original_bytes = path.stat().st_size
    wal_path = Path(str(path) + "-wal")
    shm_path = Path(str(path) + "-shm")
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    shm_bytes = shm_path.stat().st_size if shm_path.exists() else 0
    con = sqlite3.connect(path)
    try:
        table_exists = con.execute(
            "select 1 from sqlite_master where type='table' and name='logs'"
        ).fetchone()
        if not table_exists:
            raise RuntimeError(f"{path} does not contain a logs table")
        total_rows = int(con.execute("select count(*) from logs").fetchone()[0])
        old_rows, old_estimated = con.execute(
            "select count(*), coalesce(sum(estimated_bytes), 0) from logs where ts < ?",
            (cutoff_epoch,),
        ).fetchone()
        kept_rows, kept_estimated = con.execute(
            "select count(*), coalesce(sum(estimated_bytes), 0) from logs where ts >= ?",
            (cutoff_epoch,),
        ).fetchone()
    finally:
        con.close()
    return LogPruneStats(
        path=path,
        original_bytes=original_bytes,
        wal_bytes=wal_bytes,
        shm_bytes=shm_bytes,
        total_rows=total_rows,
        old_rows=int(old_rows),
        kept_rows=int(kept_rows),
        old_estimated_bytes=int(old_estimated),
        kept_estimated_bytes=int(kept_estimated),
        changed=bool(old_rows),
        backup_paths=[],
    )


def prune_logs_db(
    path: Path,
    *,
    cutoff: datetime,
    backup_root: Path,
    codex_home: Path,
    apply: bool,
    vacuum: bool,
) -> LogPruneStats | None:
    cutoff_epoch = int(cutoff.timestamp())
    stats = inspect_logs_db(path, cutoff_epoch)
    if stats is None or not apply or not stats.changed:
        return stats

    backup_paths = copy_sqlite_backups(path, backup_root, codex_home)
    con = sqlite3.connect(path)
    try:
        con.execute("delete from logs where ts < ?", (cutoff_epoch,))
        con.commit()
        con.execute("pragma wal_checkpoint(TRUNCATE)")
        if vacuum:
            con.execute("vacuum")
    finally:
        con.close()

    stats.backup_paths = backup_paths
    return stats


def log_stats_payload(stats: LogPruneStats | None) -> dict[str, object] | None:
    if stats is None:
        return None
    return {
        "path": str(stats.path),
        "originalBytes": stats.original_bytes,
        "walBytes": stats.wal_bytes,
        "shmBytes": stats.shm_bytes,
        "totalRows": stats.total_rows,
        "oldRows": stats.old_rows,
        "keptRows": stats.kept_rows,
        "oldEstimatedBytes": stats.old_estimated_bytes,
        "keptEstimatedBytes": stats.kept_estimated_bytes,
        "changed": stats.changed,
        "backupPaths": [str(path) for path in stats.backup_paths],
    }


def write_combined_report(
    report_path: Path,
    session_stats: list[PruneStats],
    *,
    log_stats: LogPruneStats | None,
    cutoff: datetime,
    apply: bool,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "apply" if apply else "dry-run",
        "cutoff": cutoff.isoformat(),
        "sessions": [
            {
                "path": str(item.path),
                "originalBytes": item.original_bytes,
                "keptBytes": item.kept_bytes,
                "archivedBytes": item.archived_bytes,
                "totalLines": item.total_lines,
                "keptLines": item.kept_lines,
                "archivedLines": item.archived_lines,
                "malformedLines": item.malformed_lines,
                "changed": item.changed,
                "backupPath": str(item.backup_path) if item.backup_path else None,
                "archivePath": str(item.archive_path) if item.archive_path else None,
                "error": item.error,
            }
            for item in session_stats
        ],
        "logs": log_stats_payload(log_stats),
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune Codex session JSONL files by timestamp.")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--session-root", type=Path, action="append", default=None)
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--retention-hours", type=int, default=DEFAULT_RETENTION_HOURS)
    parser.add_argument("--now", type=str, default=None, help="Override current time, ISO-8601.")
    parser.add_argument("--apply", action="store_true", help="Actually rewrite files. Default is dry-run.")
    parser.add_argument("--include-archived-sessions", action="store_true")
    parser.add_argument("--include-logs", action="store_true", help="Also prune logs_2.sqlite by the same cutoff.")
    parser.add_argument("--logs-db", type=Path, default=None, help="Override logs DB path.")
    parser.add_argument("--no-vacuum", action="store_true", help="Skip VACUUM when applying logs DB pruning.")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.retention_hours <= 0:
        parser.error("--retention-hours must be positive")

    codex_home = args.codex_home.expanduser().resolve()
    if args.session_root:
        session_roots = [root.expanduser().resolve() for root in args.session_root]
    else:
        session_roots = [codex_home / "sessions"]
        if args.include_archived_sessions:
            session_roots.append(codex_home / "archived_sessions")

    now = parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        parser.error("--now must be a valid ISO-8601 timestamp")
    cutoff = now - timedelta(hours=args.retention_hours)

    timestamp = now.strftime("%Y%m%d-%H%M%S")
    backup_root = args.backup_root or (Path.home() / "Desktop" / f"codex_session_cleanup_backup_{timestamp}")
    backup_root = backup_root.expanduser().resolve()
    report_path = args.report or backup_root / "prune_report.json"

    session_files = discover_session_files(session_roots)
    stats = [
        prune_session_file(
            path,
            cutoff=cutoff,
            backup_root=backup_root,
            codex_home=codex_home,
            apply=args.apply,
        )
        for path in session_files
    ]
    log_stats = None
    if args.include_logs:
        logs_db = (args.logs_db or codex_home / "logs_2.sqlite").expanduser().resolve()
        log_stats = prune_logs_db(
            logs_db,
            cutoff=cutoff,
            backup_root=backup_root,
            codex_home=codex_home,
            apply=args.apply,
            vacuum=not args.no_vacuum,
        )
    write_combined_report(report_path, stats, log_stats=log_stats, cutoff=cutoff, apply=args.apply)

    changed = [item for item in stats if item.changed]
    errors = [item for item in stats if item.error]
    archived_bytes = sum(item.archived_bytes for item in changed)
    kept_bytes = sum(item.kept_bytes for item in stats)
    original_bytes = sum(item.original_bytes for item in stats)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    print(f"cutoff={cutoff.isoformat()}")
    print(f"files_scanned={len(stats)}")
    print(f"files_changed={len(changed)}")
    print(f"files_errors={len(errors)}")
    print(f"original_mb={original_bytes / 1024 / 1024:.2f}")
    print(f"kept_mb={kept_bytes / 1024 / 1024:.2f}")
    print(f"archived_mb={archived_bytes / 1024 / 1024:.2f}")
    if log_stats is not None:
        print(f"logs_old_rows={log_stats.old_rows}")
        print(f"logs_kept_rows={log_stats.kept_rows}")
        print(f"logs_old_estimated_mb={log_stats.old_estimated_bytes / 1024 / 1024:.2f}")
        print(f"logs_kept_estimated_mb={log_stats.kept_estimated_bytes / 1024 / 1024:.2f}")
    print(f"report={report_path}")
    if args.apply:
        print(f"backup_root={backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
