#!/usr/bin/env python3
"""Generate a DEV PlatformFlowReadinessReport. Never starts real research."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.platform_flow_ready import (
    build_platform_flow_readiness_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a DEV PlatformFlowReadinessReport.")
    parser.add_argument("--repo", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--clone-dest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = build_platform_flow_readiness_report(args.repo, clone_dest=args.clone_dest)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
