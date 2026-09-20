# -*- coding: utf-8 -*-
"""Cross-session fix ledger: structured record of defects, errata and recipes.

跨会话共享的修复知识库。三类条目::

    defect  缺陷根因（症状 → 根因 → 修复锚点）
    erratum 误诊勘误（曾经被当成 bug / 被误诊的结论，防止重新踩一遍）
    recipe  排障配方（可复用的诊断 / 恢复 / 收口操作序列）

存储：Git common-dir 下的 ``vibelution-cache/fix_ledger/entries.jsonl``
（append-only JSONL，与 reuse_research 同根；本机跨会话共享，不入版本控制）。

用法::

    python scripts/fix_ledger.py record --category erratum --severity high \\
        --symptom "..." --root-cause "..." --lesson "..." \\
        [--fix-sha abc1234] [--files a.py b.py] [--tags net cli]
    python scripts/fix_ledger.py query --keyword fallback --files config/ --limit 5
    python scripts/fix_ledger.py list --limit 10
    python scripts/fix_ledger.py import --file scripts/fix_ledger_seed.jsonl

自愿登记，不接任何门禁；任务收口时把值得跨会话记住的结论留一条即可。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

CATEGORIES = ("defect", "erratum", "recipe")
SEVERITIES = ("high", "medium", "low")
_TEXT_LIMIT = 600
_SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE)


class FixLedgerError(ValueError):
    """Typed fail-closed error for ledger operations."""


def _git_common_dir(root: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise FixLedgerError(f"not a git repository: {root}")
    return (root / completed.stdout.strip()).resolve()


def ledger_path(root: Path) -> Path:
    return _git_common_dir(root) / "vibelution-cache" / "fix_ledger" / "entries.jsonl"


def _text(value: Any, *, field: str, required: bool = True, limit: int = _TEXT_LIMIT) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if required and not normalized:
        raise FixLedgerError(f"{field} is required.")
    if len(normalized) > limit:
        raise FixLedgerError(f"{field} exceeds {limit} characters.")
    if _SECRET_RE.search(normalized):
        raise FixLedgerError(f"{field} must not contain secrets.")
    return normalized


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue  # 单行损坏不拖垮整本账
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _append_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _next_id(entries: Sequence[dict[str, Any]]) -> str:
    highest = 0
    for entry in entries:
        match = re.match(r"^fxl-(\d+)$", str(entry.get("id") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"fxl-{highest + 1:04d}"


def record_entry(
    root: Path,
    *,
    category: str,
    severity: str,
    symptom: str,
    root_cause: str,
    lesson: str = "",
    fix_sha: str = "",
    files: Sequence[str] = (),
    tags: Sequence[str] = (),
    source: str = "session",
) -> dict[str, Any]:
    if category not in CATEGORIES:
        raise FixLedgerError(f"category must be one of {CATEGORIES}")
    if severity not in SEVERITIES:
        raise FixLedgerError(f"severity must be one of {SEVERITIES}")
    entry = {
        "id": _next_id(_load_entries(ledger_path(root))),
        "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "category": category,
        "severity": severity,
        "symptom": _text(symptom, field="symptom"),
        "rootCause": _text(root_cause, field="root-cause"),
        "lesson": _text(lesson, field="lesson", required=False),
        "fixSha": _text(fix_sha, field="fix-sha", required=False, limit=40),
        "files": sorted({_text(f, field="files", required=False, limit=200) for f in files if str(f).strip()}),
        "tags": sorted({_text(t, field="tags", required=False, limit=60).lower() for t in tags if str(t).strip()}),
        "source": _text(source, field="source", required=False, limit=40),
    }
    _append_entry(ledger_path(root), entry)
    return entry


def query_entries(
    root: Path,
    *,
    keywords: Sequence[str] = (),
    files: Sequence[str] = (),
    tags: Sequence[str] = (),
    category: str = "",
    severity: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    entries = _load_entries(ledger_path(root))
    keywords_normalized = [k.lower() for k in keywords if k.strip()]
    tags_normalized = [t.lower() for t in tags if t.strip()]
    results: list[dict[str, Any]] = []
    for entry in entries:
        haystack = " ".join(
            str(entry.get(field) or "") for field in ("symptom", "rootCause", "lesson", "tags")
        ).lower()
        if keywords_normalized and not any(k in haystack for k in keywords_normalized):
            continue
        if tags_normalized and not any(t in [str(t).lower() for t in entry.get("tags") or []] for t in tags_normalized):
            continue
        if category and str(entry.get("category") or "") != category:
            continue
        if severity and str(entry.get("severity") or "") != severity:
            continue
        entry_files = [str(f) for f in entry.get("files") or []]
        if files and not any(
            any(f == ef or ef.startswith(f.rstrip("/\\") + "/") or f.startswith(ef.rstrip("/\\") + "/") for ef in entry_files)
            for f in files
        ):
            continue
        results.append(entry)
    return list(reversed(results))[: max(1, limit)]


def import_entries(root: Path, seed_file: Path) -> dict[str, int]:
    """Append seed entries, skipping exact symptom+rootCause duplicates."""

    if not seed_file.is_file():
        raise FixLedgerError(f"seed file not found: {seed_file}")
    existing = _load_entries(ledger_path(root))
    seen = {(str(e.get("symptom") or ""), str(e.get("rootCause") or "")) for e in existing}
    added = 0
    skipped = 0
    for line in seed_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        if (str(payload.get("symptom") or ""), str(payload.get("rootCause") or "")) in seen:
            skipped += 1
            continue
        record_entry(
            root,
            category=str(payload.get("category") or "defect"),
            severity=str(payload.get("severity") or "medium"),
            symptom=str(payload.get("symptom") or ""),
            root_cause=str(payload.get("rootCause") or ""),
            lesson=str(payload.get("lesson") or ""),
            fix_sha=str(payload.get("fixSha") or ""),
            files=[str(f) for f in payload.get("files") or []],
            tags=[str(t) for t in payload.get("tags") or []],
            source=str(payload.get("source") or "imported"),
        )
        seen.add((str(payload.get("symptom") or ""), str(payload.get("rootCause") or "")))
        added += 1
    return {"added": added, "skipped": skipped}


def render_entry(entry: dict[str, Any]) -> str:
    parts = [f"[{entry.get('id')}] {entry.get('category')}/{entry.get('severity')} · {entry.get('symptom')}"]
    parts.append(f"    根因: {entry.get('rootCause')}")
    if entry.get("lesson"):
        parts.append(f"    要点: {entry.get('lesson')}")
    extras: list[str] = []
    if entry.get("fixSha"):
        extras.append(f"fix={entry.get('fixSha')}")
    if entry.get("files"):
        extras.append("files: " + ", ".join(entry.get("files") or [])[:160])
    if entry.get("tags"):
        extras.append("tags: " + ", ".join(entry.get("tags") or []))
    if extras:
        parts.append("    " + " · ".join(extras))
    return "\n".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-session fix ledger (defects / errata / recipes).")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="Append one entry.")
    record_parser.add_argument("--category", required=True, choices=CATEGORIES)
    record_parser.add_argument("--severity", required=True, choices=SEVERITIES)
    record_parser.add_argument("--symptom", required=True)
    record_parser.add_argument("--root-cause", required=True)
    record_parser.add_argument("--lesson", default="")
    record_parser.add_argument("--fix-sha", default="")
    record_parser.add_argument("--files", nargs="*", default=[])
    record_parser.add_argument("--tags", nargs="*", default=[])
    record_parser.add_argument("--source", default="session")

    query_parser = subparsers.add_parser("query", help="Search entries.")
    query_parser.add_argument("--keyword", nargs="*", default=[])
    query_parser.add_argument("--files", nargs="*", default=[])
    query_parser.add_argument("--tags", nargs="*", default=[])
    query_parser.add_argument("--category", choices=CATEGORIES, default="")
    query_parser.add_argument("--severity", choices=SEVERITIES, default="")
    query_parser.add_argument("--limit", type=int, default=10)

    list_parser = subparsers.add_parser("list", help="List recent entries.")
    list_parser.add_argument("--limit", type=int, default=10)

    import_parser = subparsers.add_parser("import", help="Import a seed JSONL file (idempotent).")
    import_parser.add_argument("--file", required=True)

    arguments = parser.parse_args(argv)
    root = Path(arguments.project_root).resolve()
    try:
        if arguments.command == "record":
            entry = record_entry(
                root,
                category=arguments.category,
                severity=arguments.severity,
                symptom=arguments.symptom,
                root_cause=arguments.root_cause,
                lesson=arguments.lesson,
                fix_sha=arguments.fix_sha,
                files=arguments.files,
                tags=arguments.tags,
                source=arguments.source,
            )
            print(json.dumps({"ok": True, "id": entry["id"], "path": str(ledger_path(root))}, ensure_ascii=False))
        elif arguments.command == "query":
            entries = query_entries(
                root,
                keywords=arguments.keyword,
                files=arguments.files,
                tags=arguments.tags,
                category=arguments.category,
                severity=arguments.severity,
                limit=arguments.limit,
            )
            if not entries:
                print("(no matching entries)")
            for entry in entries:
                print(render_entry(entry))
        elif arguments.command == "list":
            entries = query_entries(root, limit=arguments.limit)
            if not entries:
                print("(ledger is empty)")
            for entry in entries:
                print(render_entry(entry))
        elif arguments.command == "import":
            summary = import_entries(root, Path(arguments.file))
            print(json.dumps({"ok": True, **summary}, ensure_ascii=False))
    except FixLedgerError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
