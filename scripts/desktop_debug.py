#!/usr/bin/env python3
"""Print the verified local Electron CDP endpoint and current page targets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.launcher.desktop_debug import discover_desktop_debug


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(discover_desktop_debug(args.project), ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as exc:
        print(json.dumps({"available": False, "reason": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
