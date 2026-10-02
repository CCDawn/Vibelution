#!/usr/bin/env python3
"""Bounded Python owner for the Electron package build command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.launcher.desktop_shell import build_desktop_shell_package, build_unpackaged_desktop_shell  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dir", "staging", "linux-arm64", "unpackaged"), required=True)
    args = parser.parse_args(argv)
    try:
        result = (build_unpackaged_desktop_shell(PROJECT_ROOT) if args.mode == "unpackaged"
                  else build_desktop_shell_package(PROJECT_ROOT, mode=args.mode))
    except Exception as exc:
        print(f"Desktop package build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
