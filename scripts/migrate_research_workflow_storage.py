#!/usr/bin/env python3
"""受管迁移 operator Documents/research_workflows 到项目 canonical root。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.research_workflow_storage_migration import (
    ResearchWorkflowMigrationError,
    apply_research_workflow_migration,
    preview_research_workflow_migration,
    rollback_research_workflow_migration,
    verify_research_workflow_migration,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "apply", "verify", "rollback"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--project", default=str(PROJECT_ROOT))
        sub.add_argument("--manifest", default="")
        sub.add_argument("--json", action="store_true", help="输出 JSON（默认也是 JSON，保留兼容开关）")
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve() if args.manifest else None
    try:
        if args.command == "preview":
            result = preview_research_workflow_migration(project)
            payload = result.to_dict()
        elif args.command == "apply":
            payload = apply_research_workflow_migration(project)
        elif args.command == "verify":
            payload = verify_research_workflow_migration(project, manifest_path=manifest)
        else:
            payload = rollback_research_workflow_migration(project, manifest_path=manifest)
    except ResearchWorkflowMigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.command == "preview":
        return 0 if payload.get("ok") else 1
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
