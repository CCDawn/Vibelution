#!/usr/bin/env python3
"""Check a PDF byte size against the contest limit without generating content."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.delivery import check_pdf_limit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a PDF size against the Challenge Cup limit.")
    parser.add_argument("--size-bytes", type=int, required=True)
    parser.add_argument("--limit-bytes", type=int)
    args = parser.parse_args(argv)
    kwargs = {}
    if args.limit_bytes is not None:
        kwargs["limit_bytes"] = args.limit_bytes
    report = check_pdf_limit(args.size_bytes, **kwargs)
    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if report["withinLimit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
