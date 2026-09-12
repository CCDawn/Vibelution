#!/usr/bin/env python3
"""会话账本体检报告（严格只读）。

用途：在决定"账本是否需要物理归档"之前，先看清真实数据：
- 账本总量与大小分布（Top N）
- 按权威冷信号分组：活跃 / 冷（未软归档）/ 已软归档 / 运行中守卫
- 孤儿账本（有文件、目录无行）与缺失账本（有目录行、无文件）
- 归档候选预估（仅报告，绝不移动文件）

权威字段：`sessions.recency_at_ms`（会话新鲜度）与 `sessions.archived_at_ms`
（软归档）。不要用 `sessions.updated_at_ms` 作冷信号——后台索引与状态对账
都会刷新它，它不代表用户活跃度。

本脚本不写入、不移动、不删除任何文件；SQLite 以 mode=ro 只读打开。

用法示例:
    python scripts/report_session_ledgers.py
    python scripts/report_session_ledgers.py --cold-days 60 --top 15
    python scripts/report_session_ledgers.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.chat.turn_journal import turn_journal_path, turn_journal_workspace_root
from core.infrastructure import developer_sandbox


_RUNNING_GUARD_STATUSES = {"running", "queued", "stopping", "paused"}
_MS_PER_DAY = 86_400_000
_GROUP_ORDER = ("active", "cold", "archived", "running", "missing", "orphan")


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}{units[-1]}"


def _read_session_rows(sqlite_path: Path) -> tuple[list[dict[str, Any]], str]:
    """只读打开 SQLite 目录；返回 (rows, error)。"""
    if not sqlite_path.exists():
        return [], f"missing:{sqlite_path}"
    try:
        uri = f"file:{sqlite_path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT session_id, agent_id, status, recency_at_ms, archived_at_ms,"
                " hidden_from_index, session_kind, session_role, title"
                " FROM sessions"
            )
            return [dict(row) for row in cursor.fetchall()], ""
    except sqlite3.Error as exc:
        return [], f"sqlite_error:{exc}"


def _scan_ledger_files(sessions_root: Path) -> dict[str, int]:
    """扫描 sessions 根，返回 {目录token: 账本字节数}。"""
    entries: dict[str, int] = {}
    if not sessions_root.exists():
        return entries
    for child in sessions_root.iterdir():
        if not child.is_dir():
            continue
        journal = child / "turn_journal.jsonl"
        try:
            if not journal.is_file():
                continue
            entries[child.name] = int(journal.stat().st_size)
        except OSError:
            continue
    return entries


def collect_ledger_report(
    project_root: Path,
    *,
    cold_days: int = 90,
    top: int = 10,
    sessions_root: Path | None = None,
    sqlite_path: Path | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    resolved_sessions_root = (
        Path(sessions_root) if sessions_root is not None
        else turn_journal_workspace_root(project_root)
    )
    resolved_sqlite_path = (
        Path(sqlite_path) if sqlite_path is not None
        else developer_sandbox.sandboxed_workspace_path(
            project_root, "chat", "conversations.sqlite3"
        )
    )
    resolved_now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    cold_cutoff_ms = resolved_now_ms - max(0, int(cold_days)) * _MS_PER_DAY

    rows, sqlite_error = _read_session_rows(resolved_sqlite_path)
    scanned = _scan_ledger_files(resolved_sessions_root)

    groups: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("active", "cold", "archived", "running", "missing")
    }
    referenced_tokens: set[str] = set()
    for row in rows:
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue
        journal_path = turn_journal_path(
            project_root,
            session_id,
            journal_workspace_root=resolved_sessions_root,
        )
        token = journal_path.parent.name
        referenced_tokens.add(token)
        size_bytes = scanned.get(token)
        status = str(row.get("status") or "")
        archived_at = row.get("archived_at_ms")
        recency_at_ms = int(row.get("recency_at_ms") or 0)
        record = {
            "sessionId": session_id,
            "token": token,
            "sizeBytes": size_bytes or 0,
            "status": status,
            "recencyAtMs": recency_at_ms,
            "archived": archived_at is not None,
            "hiddenFromIndex": bool(row.get("hidden_from_index")),
            "sessionKind": str(row.get("session_kind") or ""),
            "sessionRole": str(row.get("session_role") or ""),
            "title": str(row.get("title") or ""),
        }
        if size_bytes is None:
            groups["missing"].append(record)
        elif status in _RUNNING_GUARD_STATUSES:
            groups["running"].append(record)
        elif archived_at is not None:
            groups["archived"].append(record)
        elif recency_at_ms and recency_at_ms < cold_cutoff_ms:
            groups["cold"].append(record)
        else:
            groups["active"].append(record)

    orphan = [
        {"token": token, "sizeBytes": size}
        for token, size in scanned.items()
        if token not in referenced_tokens
    ]

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "totalBytes": sum(int(item.get("sizeBytes") or 0) for item in items),
        }

    def top_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(items, key=lambda item: int(item.get("sizeBytes") or 0), reverse=True)
        return ordered[: max(1, int(top))]

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectRoot": str(project_root),
        "sessionsRoot": str(resolved_sessions_root),
        "sqlitePath": str(resolved_sqlite_path),
        "sqliteError": sqlite_error,
        "coldDays": int(cold_days),
        "totals": {
            "scannedFiles": len(scanned),
            "scannedBytes": sum(scanned.values()),
            "directoryRows": len(rows),
        },
        "groups": {name: summarize(groups[name]) for name in groups},
        "orphan": summarize([{"sizeBytes": item["sizeBytes"]} for item in orphan]),
        "topLedgers": top_items(
            [{"token": token, "sizeBytes": size} for token, size in scanned.items()]
        ),
        "archivalCandidates": {
            "archived": {
                "summary": summarize(groups["archived"]),
                "top": top_items(groups["archived"]),
            },
            "cold": {
                "summary": summarize(groups["cold"]),
                "top": top_items(groups["cold"]),
            },
        },
        "orphanLedgers": top_items(orphan),
        "missingLedgers": top_items(groups["missing"]),
    }


def render_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("会话账本体检报告（只读；本报告不会移动或删除任何文件）")
    lines.append(f"  生成时间: {report['generatedAt']}")
    lines.append(f"  sessions 根: {report['sessionsRoot']}")
    sqlite_state = report["sqliteError"] or "ok"
    lines.append(f"  SQLite 目录: {report['sqlitePath']}  [{sqlite_state}]")
    totals = report["totals"]
    lines.append(
        f"  账本文件: {totals['scannedFiles']} 个 / {_human_size(totals['scannedBytes'])}"
        f"；目录行: {totals['directoryRows']}"
    )
    lines.append("")

    lines.append("大小 Top:")
    for item in report["topLedgers"]:
        lines.append(f"  {_human_size(int(item['sizeBytes'])):>8}  {item['token']}")
    lines.append("")

    lines.append(f"分组（冷阈值 {report['coldDays']} 天，按 recency_at_ms / archived_at_ms）:")
    labels = {
        "active": "活跃",
        "cold": "冷（未软归档）",
        "archived": "已软归档",
        "running": "运行中守卫",
        "missing": "缺失（有行无文件）",
    }
    for name in ("active", "cold", "archived", "running", "missing"):
        summary = report["groups"][name]
        lines.append(
            f"  {labels[name]}: {summary['count']} 个 / {_human_size(int(summary['totalBytes']))}"
        )
    orphan_summary = report["orphan"]
    lines.append(
        f"  孤儿账本（有文件、目录无行）: {orphan_summary['count']} 个 / "
        f"{_human_size(int(orphan_summary['totalBytes']))}"
    )
    lines.append("")

    candidates = report["archivalCandidates"]
    lines.append("归档候选预估（只报告；正式归档机制需另行设计与对齐）:")
    for name, label in (("archived", "已软归档会话"), ("cold", "冷会话")):
        summary = candidates[name]["summary"]
        lines.append(
            f"  [{label}] {summary['count']} 个 / {_human_size(int(summary['totalBytes']))}"
        )
        for item in candidates[name]["top"]:
            title = item.get("title") or ""
            suffix = f"  {title}" if title else ""
            lines.append(
                f"      {_human_size(int(item['sizeBytes'])):>8}  {item['sessionId']}{suffix}"
            )
    if report["missingLedgers"]:
        lines.append("")
        lines.append("缺失账本（有目录行但无文件，建议人工核对）:")
        for item in report["missingLedgers"]:
            lines.append(f"      {item['sessionId']}  status={item['status']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="会话账本体检报告（只读）")
    parser.add_argument(
        "--project",
        default=str(REPO_ROOT),
        help="项目根（默认当前仓库根）",
    )
    parser.add_argument(
        "--cold-days",
        type=int,
        default=90,
        help="冷会话阈值天数（默认 90）",
    )
    parser.add_argument("--top", type=int, default=10, help="每组展示条数（默认 10）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    report = collect_ledger_report(
        Path(args.project),
        cold_days=args.cold_days,
        top=args.top,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
