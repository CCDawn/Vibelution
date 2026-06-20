#!/usr/bin/env python3
"""Move Vibelution product workspace data into the user-level data home.

The migration intentionally copies data and verifies the target. It does not
delete the project-local workspace; cleanup should be a separate explicit step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.paths import resolve_workspace_home  # noqa: E402
from core.web.services.workspace_data_migration_service import (  # noqa: E402
    DEFAULT_TOP_LEVEL_EXCLUDES,
    apply_migration,
    apply_workspace_migration,
    build_report,
    finalize_external_workspace,
    preview_workspace_migration,
    verify_migration,
    verify_workspace_migration,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "apply", "verify", "finalize-target"))
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

    if args.action == "dry-run":
        report = preview_workspace_migration(
            project_root=project_root,
            data_home=args.data_home or None,
            config_path=args.config_path or None,
            excludes=excludes,
        )
    elif args.action == "apply":
        report = apply_workspace_migration(
            project_root=project_root,
            data_home=args.data_home or None,
            config_path=args.config_path or None,
            excludes=excludes,
        )
    elif args.action == "finalize-target":
        report = finalize_external_workspace(
            data_home=args.data_home or None,
            config_path=args.config_path or None,
            project_root=project_root,
            excludes=excludes,
            report_path=args.report_path or None,
        )
        if not report["verification"]["ok"]:
            _write_report(args.report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
    else:
        report = verify_workspace_migration(
            project_root=project_root,
            data_home=args.data_home or None,
            config_path=args.config_path or None,
            excludes=excludes,
        )
        if not report["verified"]["ok"]:
            _write_report(args.report_path, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

    _write_report(args.report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _write_report(path_value: str, report: dict[str, Any]) -> None:
    if not str(path_value or "").strip():
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
