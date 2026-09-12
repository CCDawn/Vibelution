"""report_session_ledgers 体检逻辑测试（只读报告）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.chat.turn_journal import turn_journal_path

from scripts.report_session_ledgers import collect_ledger_report, render_report


_NOW_MS = 1_800_000_000_000
_DAY_MS = 86_400_000


def _seed_session_journal(sessions_root: Path, project_root: Path, session_id: str, content: str) -> None:
    journal_path = turn_journal_path(
        project_root,
        session_id,
        journal_workspace_root=sessions_root,
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(content, encoding="utf-8")


def _seed_sqlite(sqlite_path: Path, rows: list[dict]) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
              session_id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              status TEXT NOT NULL,
              recency_at_ms INTEGER NOT NULL,
              archived_at_ms INTEGER,
              hidden_from_index INTEGER NOT NULL DEFAULT 0,
              session_kind TEXT NOT NULL DEFAULT 'main',
              session_role TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL DEFAULT ''
            )
            """
        )
        for row in rows:
            conn.execute(
                "INSERT INTO sessions (session_id, agent_id, status, recency_at_ms,"
                " archived_at_ms, hidden_from_index, session_kind, session_role, title)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["session_id"],
                    "agent-a",
                    row.get("status", "ready"),
                    row["recency_at_ms"],
                    row.get("archived_at_ms"),
                    row.get("hidden_from_index", 0),
                    row.get("session_kind", "main"),
                    row.get("session_role", ""),
                    row.get("title", ""),
                ),
            )


def test_collect_ledger_report_groups_and_candidates(tmp_path: Path) -> None:
    sessions_root = tmp_path / "ws" / "sessions"
    sqlite_path = tmp_path / "ws" / "chat" / "conversations.sqlite3"

    _seed_session_journal(sessions_root, tmp_path, "session-active", "x" * 100)
    _seed_session_journal(sessions_root, tmp_path, "session-cold", "x" * 5000)
    _seed_session_journal(sessions_root, tmp_path, "session-archived", "x" * 3000)
    _seed_session_journal(sessions_root, tmp_path, "session-running", "x" * 200)
    _seed_session_journal(sessions_root, tmp_path, "orphan-token-dir", "x" * 50)
    _seed_sqlite(
        sqlite_path,
        [
            {"session_id": "session-active", "recency_at_ms": _NOW_MS - _DAY_MS},
            {
                "session_id": "session-cold",
                "recency_at_ms": _NOW_MS - 120 * _DAY_MS,
                "title": "冷会话",
            },
            {
                "session_id": "session-archived",
                "recency_at_ms": _NOW_MS - 200 * _DAY_MS,
                "archived_at_ms": _NOW_MS - 30 * _DAY_MS,
            },
            {
                "session_id": "session-running",
                "status": "running",
                "recency_at_ms": _NOW_MS - 2 * _DAY_MS,
            },
            {"session_id": "session-missing", "recency_at_ms": _NOW_MS - 400 * _DAY_MS},
        ],
    )

    # orphan：有文件、目录无行（目录名不会被任何 session 解析到）
    orphan_dir = sessions_root / "zz-orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "turn_journal.jsonl").write_text("y" * 70, encoding="utf-8")
    # 让上面 seeded 的 orphan-token-dir 也被计入 orphan（它没有对应目录行）
    report = collect_ledger_report(
        tmp_path,
        cold_days=90,
        top=5,
        sessions_root=sessions_root,
        sqlite_path=sqlite_path,
        now_ms=_NOW_MS,
    )

    groups = report["groups"]
    assert groups["active"]["count"] == 1
    assert groups["cold"]["count"] == 1
    assert groups["archived"]["count"] == 1
    assert groups["running"]["count"] == 1
    assert groups["missing"]["count"] == 1
    assert report["orphan"]["count"] == 2
    assert report["sqliteError"] == ""

    candidates = report["archivalCandidates"]
    assert candidates["archived"]["summary"]["count"] == 1
    assert candidates["archived"]["summary"]["totalBytes"] == 3000
    assert candidates["cold"]["summary"]["count"] == 1
    assert candidates["cold"]["summary"]["totalBytes"] == 5000
    assert candidates["cold"]["top"][0]["title"] == "冷会话"

    text = render_report(report)
    assert "会话账本体检报告" in text
    assert "已软归档" in text
    assert "session-cold" in text


def test_collect_ledger_report_without_sqlite_degrades(tmp_path: Path) -> None:
    sessions_root = tmp_path / "ws" / "sessions"
    _seed_session_journal(sessions_root, tmp_path, "session-a", "x" * 10)
    report = collect_ledger_report(
        tmp_path,
        sessions_root=sessions_root,
        sqlite_path=tmp_path / "ws" / "chat" / "conversations.sqlite3",
        now_ms=_NOW_MS,
    )

    assert report["sqliteError"].startswith("missing:")
    assert report["totals"]["directoryRows"] == 0
    assert report["orphan"]["count"] == 1
    assert report["groups"]["active"]["count"] == 0
