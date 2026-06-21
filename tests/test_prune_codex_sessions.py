from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.prune_codex_sessions import main


def _line(timestamp: str, type_: str = "event_msg") -> str:
    return json.dumps({"timestamp": timestamp, "type": type_, "payload": {"value": timestamp}}) + "\n"


def test_prune_codex_sessions_dry_run_does_not_modify_file(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    session_root = codex_home / "sessions"
    session_root.mkdir(parents=True)
    session_file = session_root / "rollout.jsonl"
    original = "".join(
        [
            _line("2026-06-01T00:00:00Z", "session_meta"),
            _line("2026-06-01T01:00:00Z"),
            _line("2026-06-05T01:00:00Z"),
        ]
    )
    session_file.write_text(original, encoding="utf-8")

    rc = main(
        [
            "--codex-home",
            str(codex_home),
            "--now",
            "2026-06-06T00:00:00Z",
            "--retention-hours",
            "72",
            "--backup-root",
            str(tmp_path / "backup"),
        ]
    )

    assert rc == 0
    assert session_file.read_text(encoding="utf-8") == original
    report = json.loads((tmp_path / "backup" / "prune_report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "dry-run"
    assert report["sessions"][0]["archivedLines"] == 1


def test_prune_codex_sessions_apply_requires_explicit_session_prune_allowance(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    session_root = codex_home / "sessions"
    session_root.mkdir(parents=True)
    session_file = session_root / "rollout.jsonl"
    original = _line("2026-06-01T01:00:00Z")
    session_file.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--codex-home",
                str(codex_home),
                "--now",
                "2026-06-06T00:00:00Z",
                "--retention-hours",
                "72",
                "--backup-root",
                str(tmp_path / "backup"),
                "--apply",
            ]
        )

    assert exc_info.value.code == 2
    assert session_file.read_text(encoding="utf-8") == original


def test_prune_codex_sessions_apply_archives_old_lines_and_keeps_meta(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    session_root = codex_home / "sessions"
    session_root.mkdir(parents=True)
    session_file = session_root / "rollout.jsonl"
    session_file.write_text(
        "".join(
            [
                _line("2026-05-01T00:00:00Z", "session_meta"),
                _line("2026-06-01T01:00:00Z"),
                _line("2026-06-05T01:00:00Z"),
                "{not-json}\n",
            ]
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "--codex-home",
            str(codex_home),
            "--now",
            "2026-06-06T00:00:00Z",
            "--retention-hours",
            "72",
            "--backup-root",
            str(tmp_path / "backup"),
            "--apply",
            "--allow-session-prune",
        ]
    )

    assert rc == 0
    rewritten = session_file.read_text(encoding="utf-8")
    assert "session_meta" in rewritten
    assert "2026-06-05T01:00:00Z" in rewritten
    assert "2026-06-01T01:00:00Z" not in rewritten
    assert "{not-json}" in rewritten

    archive_path = tmp_path / "backup" / "archived_lines" / "sessions" / "rollout.jsonl.gz"
    with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
        archived = handle.read()
    assert "2026-06-01T01:00:00Z" in archived

    backup_path = tmp_path / "backup" / "originals" / "sessions" / "rollout.jsonl"
    assert backup_path.exists()


def _create_logs_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            """
            create table logs (
                id integer primary key,
                ts integer not null,
                ts_nanos integer not null,
                level text not null,
                target text not null,
                feedback_log_body text,
                module_path text,
                file text,
                line integer,
                thread_id text,
                process_uuid text,
                estimated_bytes integer not null default 0
            )
            """
        )
        con.executemany(
            """
            insert into logs (
                ts, ts_nanos, level, target, feedback_log_body, estimated_bytes
            ) values (?, 0, 'INFO', 'test', 'body', ?)
            """,
            [
                (1780000000, 100),
                (1780500000, 200),
            ],
        )
        con.commit()
    finally:
        con.close()


def test_prune_codex_logs_dry_run_reports_without_deleting(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    logs_db = codex_home / "logs_2.sqlite"
    _create_logs_db(logs_db)

    rc = main(
        [
            "--codex-home",
            str(codex_home),
            "--session-root",
            str(codex_home / "missing-sessions"),
            "--now",
            "2026-06-06T00:00:00Z",
            "--retention-hours",
            "72",
            "--include-logs",
            "--logs-db",
            str(logs_db),
            "--backup-root",
            str(tmp_path / "backup"),
        ]
    )

    assert rc == 0
    con = sqlite3.connect(logs_db)
    try:
        assert con.execute("select count(*) from logs").fetchone()[0] == 2
    finally:
        con.close()
    report = json.loads((tmp_path / "backup" / "prune_report.json").read_text(encoding="utf-8"))
    assert report["logs"]["oldRows"] == 1
    assert report["logs"]["keptRows"] == 1
    assert not Path(str(logs_db) + "-wal").exists()
    assert not Path(str(logs_db) + "-shm").exists()


def test_prune_codex_logs_apply_deletes_old_rows_and_backs_up_db(tmp_path: Path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    logs_db = codex_home / "logs_2.sqlite"
    _create_logs_db(logs_db)

    rc = main(
        [
            "--codex-home",
            str(codex_home),
            "--session-root",
            str(codex_home / "missing-sessions"),
            "--now",
            "2026-06-06T00:00:00Z",
            "--retention-hours",
            "72",
            "--include-logs",
            "--logs-db",
            str(logs_db),
            "--backup-root",
            str(tmp_path / "backup"),
            "--apply",
        ]
    )

    assert rc == 0
    con = sqlite3.connect(logs_db)
    try:
        rows = con.execute("select ts from logs order by ts").fetchall()
    finally:
        con.close()
    assert rows == [(1780500000,)]
    assert (tmp_path / "backup" / "sqlite_originals" / "logs_2.sqlite").exists()
