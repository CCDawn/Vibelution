#!/usr/bin/env python3
"""Export / import a Vibelution team bundle from the command line.

Examples:
  python scripts/team_bundle.py export --team-id <teamId> --output team.json
  python scripts/team_bundle.py import --input team.json --dry-run
  python scripts/team_bundle.py import --input team.json
  python scripts/team_bundle.py import --input team.json --confirm   # future schema
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="team_bundle", description="Export or import a team bundle.")
    sub = parser.add_subparsers(dest="command", required=True)

    export_parser = sub.add_parser("export", help="Export one team to a bundle JSON file.")
    export_parser.add_argument("--team-id", required=True)
    export_parser.add_argument("--output", type=Path, required=True)

    import_parser = sub.add_parser("import", help="Import a bundle JSON file (dry-run first).")
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Allow importing a bundle whose schema major exceeds the supported major.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from core.web.services.team_bundle_service import (
        TeamBundleError,
        export_team_bundle,
        import_team_bundle,
    )

    try:
        if args.command == "export":
            bundle = export_team_bundle(args.team_id)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(f"Exported team bundle to {args.output} ({len(bundle['agents'])} agents).")
            return 0
        bundle = json.loads(args.input.read_text(encoding="utf-8"))
        report = import_team_bundle(bundle, dry_run=bool(args.dry_run), confirm=bool(args.confirm))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("status") == "pending":
            print("Re-run with --confirm to import this newer-schema bundle.", file=sys.stderr)
            return 2
        return 0
    except TeamBundleError as error:
        print(f"Bundle error ({error.code}): {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
