#!/usr/bin/env python3
"""Build a manifest-driven evidence index. Never copies from the working tree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.delivery import build_evidence_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Challenge Cup evidence index from a JSON entry list.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SystemExit("input must be a JSON array or an object with entries")
    index = build_evidence_index(entries)
    text = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
