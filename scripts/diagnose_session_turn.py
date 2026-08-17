from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.diagnostics.agent_log_context import build_agent_log_context  # noqa: E402
from core.diagnostics.session_turn_diagnosis import build_session_turn_diagnosis  # noqa: E402

__all__ = ["build_agent_log_context", "build_session_turn_diagnosis"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified agent log context. Pass --session-id to include turn diagnosis."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-id", default="")
    parser.add_argument("--scene-id", default="")
    parser.add_argument("--max-runtime-matches", type=int, default=20)
    args = parser.parse_args(argv)

    report = build_agent_log_context(
        args.project_root,
        session_id=args.session_id,
        turn_id=args.turn_id,
        scene_id=args.scene_id,
        max_runtime_matches=max(0, args.max_runtime_matches),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
