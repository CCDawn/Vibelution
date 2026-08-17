#!/usr/bin/env python3
"""Export a Challenge Cup result pack. Formal mode refuses incomplete catalogs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.delivery import export_results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Challenge Cup result pack from a JSON payload.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=("preview", "formal"), default="preview")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    pack = export_results(payload, mode=args.mode)
    text = json.dumps(pack, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if pack["status"] != "refused" else 1


if __name__ == "__main__":
    raise SystemExit(main())
