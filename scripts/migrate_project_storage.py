#!/usr/bin/env python3
"""Inventory, apply, or roll back Vibelution's external storage switch."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.storage_migration import (
    StorageMigrationError,
    apply_storage_migration,
    assess_storage_migration_readiness,
    plan_storage_migration,
    rollback_storage_switch,
)
from vibelution_storage import resolve_active_project_storage_paths, resolve_project_storage_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "readiness", "apply", "rollback"))
    parser.add_argument("--project", default=str(PROJECT_ROOT))
    parser.add_argument("--projects-home", default="")
    parser.add_argument("--config-path", default="")
    parser.add_argument("--include-entries", action="store_true")
    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    projects_home = args.projects_home or None
    config_path = args.config_path or None
    try:
        if args.action == "inventory":
            payload = plan_storage_migration(
                project,
                projects_home=projects_home,
                config_path=config_path,
            ).to_dict(include_entries=args.include_entries)
            payload["targetPaths"] = resolve_project_storage_paths(
                project,
                projects_home=projects_home,
            ).as_dict()
            payload["activePaths"] = resolve_active_project_storage_paths(
                project,
                projects_home=projects_home,
                config_path=config_path,
            ).as_dict()
        elif args.action == "readiness":
            payload = assess_storage_migration_readiness(
                project,
                projects_home=projects_home,
                config_path=config_path,
                action="apply",
            )
            print(json.dumps({"ok": bool(payload.get("ready")), **payload}, ensure_ascii=False, indent=2))
            return 0 if payload.get("ready") else 1
        elif args.action == "apply":
            payload = apply_storage_migration(
                project,
                projects_home=projects_home,
                config_path=config_path,
            )
        else:
            payload = rollback_storage_switch(project, projects_home=projects_home)
    except StorageMigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
