#!/usr/bin/env python3
"""Print the verified local Electron CDP endpoint and current page targets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.launcher.desktop_debug import (
    DesktopDebugError,
    discover_assistant_debug,
    discover_desktop_debug,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--project", type=Path, default=PROJECT_ROOT)
    modes.add_argument("--assistant-user-data", type=Path)
    args = parser.parse_args(argv)
    try:
        result = discover_assistant_debug(args.assistant_user_data) if args.assistant_user_data is not None else discover_desktop_debug(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except DesktopDebugError as exc:
        print(json.dumps({"available": False, "reason": str(exc)}, ensure_ascii=False))
        return 1
    except (RuntimeError, OSError, ValueError, TypeError):
        print(json.dumps({"available": False, "reason": "Desktop debugging discovery failed."}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
