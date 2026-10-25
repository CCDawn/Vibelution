#!/usr/bin/env python3
"""Read-only inventory of legacy PA sources. Does not prepare/apply migration."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assistant_runtime.migration_inventory import InventoryError, inventory_sources
from vibelution_storage import resolve_active_project_storage_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    try:
        paths = resolve_active_project_storage_paths(args.project.resolve())
        report = inventory_sources(project_root=paths.project_root, workspace=paths.data / "workspace",
            project_id=paths.project_id, instance_id=paths.instance_id)
    except (InventoryError, OSError, ValueError):
        print(json.dumps({"ok": False, "code": "SOURCE_INVENTORY_UNAVAILABLE"}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
