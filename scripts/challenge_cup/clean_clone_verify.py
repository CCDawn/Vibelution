#!/usr/bin/env python3
"""Verify Challenge Cup R0/R1 against a clean git archive, not the dirty worktree."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research.competition.source_boundary import evaluate_clean_clone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive HEAD and verify Challenge Cup source integrity plus clone hashes."
    )
    parser.add_argument("--repo", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--run-pytest", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    dest = args.dest or (args.repo / ".runtime" / "challenge-cup-clean-clone")
    report = evaluate_clean_clone(
        args.repo,
        dest,
        require_clean=args.require_clean,
        run_pytest=args.run_pytest,
        python=args.python,
    )
    payload = {
        key: value
        for key, value in report.items()
        if key != "manifest" or args.output is None
    }
    if args.output is not None:
        args.output.write_text(
            json.dumps({**payload, "manifest": report["manifest"]}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    ok = (
        report["source_integrity"] == "PASS"
        and report["clean_clone_reproduction"] == "PASS"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
