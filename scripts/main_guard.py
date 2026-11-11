"""Refuse to work while the shared main checkout is dirty.

The closeout path already treats a dirty main as a hard stop, but it only
speaks after a task is finished, which is the worst moment to discover that a
foreign session left edits behind. This guard runs the same attribution up
front so a session can fail fast and name an owner instead of silently
blocking every other task.

Exit codes: ``0`` clean, ``1`` dirty, ``2`` could not inspect.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import local_quality_gate as gate
from scripts import task_closeout

SCHEMA_VERSION = 1
EXIT_CLEAN = 0
EXIT_DIRTY = 1
EXIT_FAILED = 2


def resolve_main_checkout(start: Path) -> Path:
    """Return the checkout that owns ``refs/heads/main`` for this repository.

    Running from a task worktree must still inspect the shared main checkout,
    so resolve through the common git dir instead of the current toplevel.
    """

    completed = gate.run_process(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        start,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git rev-parse failed")
    common_dir = Path(completed.stdout.strip())
    if common_dir.name == ".git":
        return common_dir.parent
    return start


def inspect_main_checkout(repo_root: Path) -> dict[str, Any]:
    """Report whether ``repo_root`` has uncommitted work and who likely owns it."""

    context = task_closeout.CloseoutContext(
        main_root=repo_root,
        task_root=repo_root,
        branch="main",
    )
    attribution = task_closeout.describe_dirty_main(context)
    file_lines = list(attribution.file_lines)
    owners = [
        line.split("dirty_main_suspected_owner:", 1)[1].strip()
        for line in attribution.owner_lines
        if "dirty_main_suspected_owner:" in line
    ]
    dirty = bool(file_lines)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "dirty" if dirty else "clean",
        "repoRoot": str(repo_root),
        "fileLines": file_lines,
        "owners": owners,
        "nextAction": attribution.next_action if dirty else "",
    }


def _render(payload: dict[str, Any]) -> str:
    if payload["status"] == "clean":
        return f"main_guard: clean ({payload['repoRoot']})"
    lines = [f"main_guard: dirty ({payload['repoRoot']})"]
    lines.extend(payload["fileLines"])
    lines.extend(f"dirty_main_suspected_owner: {owner}" for owner in payload["owners"])
    lines.append(f"main_guard: {payload['nextAction']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail fast when the shared main checkout has uncommitted work."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Any path inside the repository; defaults to this script's checkout.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON payload.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start = args.repo or PROJECT_ROOT
    try:
        repo_root = resolve_main_checkout(start.resolve())
        payload = inspect_main_checkout(repo_root)
    except (OSError, RuntimeError, ValueError) as error:
        failure = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "failed",
            "repoRoot": str(start),
            "message": str(error),
        }
        print(json.dumps(failure, ensure_ascii=False) if args.json else f"main_guard: failed to inspect main ({error})")
        return EXIT_FAILED
    print(json.dumps(payload, ensure_ascii=False) if args.json else _render(payload))
    return EXIT_CLEAN if payload["status"] == "clean" else EXIT_DIRTY


if __name__ == "__main__":
    raise SystemExit(main())
