#!/usr/bin/env python3
"""Unified agent log context entrypoint for all development agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.diagnostics.agent_log_context import build_agent_log_context  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Return unified agent log context: active paths, current runtime scene, and optional session turn diagnosis."
    )
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-id", default="")
    parser.add_argument("--scene-id", default="")
    parser.add_argument("--recent-scene-limit", type=int, default=3)
    parser.add_argument("--max-runtime-matches", type=int, default=20)
    args = parser.parse_args(argv)

    payload = build_agent_log_context(
        args.project,
        session_id=args.session_id,
        turn_id=args.turn_id,
        scene_id=args.scene_id,
        recent_scene_limit=max(1, args.recent_scene_limit),
        max_runtime_matches=max(0, args.max_runtime_matches),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
