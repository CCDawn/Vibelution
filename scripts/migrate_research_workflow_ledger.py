"""ONE-SHOT operator CLI for Workflow Ledger migration (spec §14.3).

Not imported by the product runtime or CI. Keep this file under scripts/
because --project-root defaults to Path(__file__).resolve().parents[1].
Never defaults to the operator Documents data-root inside tests. Callers must
pass --data-root explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.research.workflow.migration.importer import apply_migration
from core.research.workflow.migration.inventory import build_inventory
from core.research.workflow.migration.manifest import AUDIT_NAME, migration_dir, write_json
from core.research.workflow.migration.validator import unknown_entries
from core.research.workflow.migration.verifier import verify_migration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="挑战杯科研工作流 Ledger 一次性迁移")
    sub = parser.add_subparsers(dest="command", required=True)

    dry = sub.add_parser("dry-run", help="Classify every legacy Run; refuse unknown labels")
    dry.add_argument("--data-root", type=Path, required=True)
    dry.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    dry.add_argument("--workspace-root", type=Path, default=None)
    dry.add_argument("--report", type=Path, default=None)

    apply_cmd = sub.add_parser("apply", help="Backup, import migratable Runs, activate Ledger")
    apply_cmd.add_argument("--data-root", type=Path, required=True)
    apply_cmd.add_argument("--backup-root", type=Path, required=True)
    apply_cmd.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    apply_cmd.add_argument("--workspace-root", type=Path, default=None)
    apply_cmd.add_argument("--report", type=Path, default=None)

    verify_cmd = sub.add_parser("verify", help="Recount imported Ledger rows against apply report")
    verify_cmd.add_argument("--data-root", type=Path, required=True)
    verify_cmd.add_argument("--report", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "dry-run":
            report = build_inventory(
                args.data_root,
                project_root=args.project_root,
                workspace_root=args.workspace_root,
            )
            unknown = unknown_entries(list(report.get("runs") or []))
            if args.report:
                write_json(args.report, report)
            else:
                write_json(migration_dir(args.data_root) / AUDIT_NAME, report)
            print(json.dumps({"unknownCount": len(unknown), "runCount": report["summary"]["runCount"]}))
            return 0 if not unknown else 1
        if args.command == "apply":
            report = apply_migration(
                args.data_root,
                project_root=args.project_root,
                backup_root=args.backup_root,
                workspace_root=args.workspace_root,
            )
            if args.report:
                write_json(args.report, report)
            print(json.dumps({"importedCount": report["importedCount"], "lineageHash": report["lineageHash"]}))
            return 0
        report = verify_migration(args.data_root)
        if args.report:
            write_json(args.report, report)
        print(json.dumps({"ok": True, "importedCount": report["importedCount"]}))
        return 0
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
