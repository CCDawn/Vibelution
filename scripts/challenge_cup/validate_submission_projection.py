#!/usr/bin/env python3
"""Validate whether Challenge Cup submission projection may freeze a formal pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.delivery import validate_submission_projection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Challenge Cup submission projection freeze state.")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    report = validate_submission_projection(json.loads(args.input.read_text(encoding="utf-8")))
    sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return 0 if not report["blocksFormalPack"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
