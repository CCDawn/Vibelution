#!/usr/bin/env python3
"""Generate a Challenge Cup source manifest from git ls-files and content hashes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.source_boundary import (
    SourceBoundaryError,
    build_source_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Challenge Cup R0 source manifest from git ls-files."
    )
    parser.add_argument("--repo", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_source_manifest(args.repo, require_clean=args.require_clean)
    except SourceBoundaryError as exc:
        sys.stdout.write(
            json.dumps({"source_integrity": "FAIL", "failures": [str(exc)]}, indent=2)
            + "\n"
        )
        return 1
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
