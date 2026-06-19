#!/usr/bin/env python3
"""Move Vibelution product workspace data into the user-level data home.

The migration intentionally copies data and verifies the target. It does not
delete the project-local workspace; cleanup should be a separate explicit step.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import resolve_data_backup_dir, resolve_workspace_home  # noqa: E402


DEFAULT_TOP_LEVEL_EXCLUDES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "apply", "verify"))
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--data-home", default="")
    parser.add_argument("--config-path", default="")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).expanduser().resolve()
    target_workspace = resolve_workspace_home(args.data_home or None, config_path=args.config_path or None)
    source_workspace = (project_root / "workspace").resolve()
    excludes = set(DEFAULT_TOP_LEVEL_EXCLUDES)
    excludes.update(str(item or "").strip() for item in args.exclude if str(item or "").strip())

    if source_workspace == target_workspace:
        raise SystemExit("Source and target workspace are the same path; migration is not needed.")

    report = build_report(
        action=args.action,
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        excludes=excludes,
    )
    if args.action == "apply":
        apply_migration(report, data_home=args.data_home or None, config_path=args.config_path or None)
        report = build_report(
            action=args.action,
            source_workspace=source_workspace,
            target_workspace=target_workspace,
            excludes=excludes,
        )
        report["applied"] = True
    elif args.action == "verify":
        report["verified"] = verify_migration(report)
        if not report["verified"]["ok"]:
            _write_report(args.report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

    _write_report(args.report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_report(*, action: str, source_workspace: Path, target_workspace: Path, excludes: set[str]) -> dict[str, Any]:
    entries = _top_level_entries(source_workspace, excludes=excludes)
    items = []
    for source in entries:
        relative = source.relative_to(source_workspace)
        target = target_workspace / relative
        items.append(
            {
                "relativePath": relative.as_posix(),
                "kind": "directory" if source.is_dir() else "file",
                "sourcePath": str(source),
                "targetPath": str(target),
                "sourceExists": source.exists(),
                "targetExists": target.exists(),
                "source": _path_summary(source),
                "target": _path_summary(target),
            }
        )
    totals = {
        "itemCount": len(items),
        "sourceSizeBytes": sum(int((item.get("source") or {}).get("sizeBytes") or 0) for item in items),
        "targetSizeBytes": sum(int((item.get("target") or {}).get("sizeBytes") or 0) for item in items),
        "targetExistingCount": sum(1 for item in items if item.get("targetExists")),
    }
    return {
        "schemaVersion": 1,
        "action": action,
        "generatedAt": _now_iso(),
        "sourceWorkspace": str(source_workspace),
        "targetWorkspace": str(target_workspace),
        "sourceExists": source_workspace.exists(),
        "targetExists": target_workspace.exists(),
        "excludes": sorted(excludes),
        "items": items,
        "totals": totals,
        "applied": False,
        "verified": {},
        "deletesProjectWorkspace": False,
    }


def apply_migration(report: dict[str, Any], *, data_home: str | None = None, config_path: str | None = None) -> None:
    backup_root = resolve_data_backup_dir(data_home, config_path=config_path) / f"workspace-migration-{_timestamp()}"
    target_workspace = Path(str(report.get("targetWorkspace") or "")).resolve()
    target_workspace.mkdir(parents=True, exist_ok=True)
    for item in list(report.get("items") or []):
        source = Path(str(item.get("sourcePath") or ""))
        target = Path(str(item.get("targetPath") or ""))
        if not source.exists():
            continue
        if target.exists():
            backup_target = backup_root / "workspace" / Path(str(item.get("relativePath") or ""))
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, backup_target, dirs_exist_ok=True)
            else:
                shutil.copy2(target, backup_target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    report["backupRoot"] = str(backup_root)


def verify_migration(report: dict[str, Any]) -> dict[str, Any]:
    mismatches = []
    for item in list(report.get("items") or []):
        source = Path(str(item.get("sourcePath") or ""))
        target = Path(str(item.get("targetPath") or ""))
        source_summary = _path_summary(source)
        target_summary = _path_summary(target)
        if source_summary != target_summary:
            mismatches.append(
                {
                    "relativePath": str(item.get("relativePath") or ""),
                    "source": source_summary,
                    "target": target_summary,
                }
            )
    return {"ok": not mismatches, "mismatchCount": len(mismatches), "mismatches": mismatches[:50]}


def _top_level_entries(source_workspace: Path, *, excludes: set[str]) -> list[Path]:
    if not source_workspace.exists():
        return []
    return [
        item
        for item in sorted(source_workspace.iterdir(), key=lambda path: path.name.casefold())
        if item.name not in excludes
    ]


def _path_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "kind": "", "fileCount": 0, "sizeBytes": 0}
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return {"exists": True, "kind": "file", "fileCount": 1, "sizeBytes": int(size)}
    file_count = 0
    size_bytes = 0
    for child in path.rglob("*"):
        if not child.is_file():
            continue
        file_count += 1
        try:
            size_bytes += child.stat().st_size
        except OSError:
            continue
    return {"exists": True, "kind": "directory", "fileCount": file_count, "sizeBytes": int(size_bytes)}


def _write_report(path_value: str, report: dict[str, Any]) -> None:
    if not str(path_value or "").strip():
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
