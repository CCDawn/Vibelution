"""Startup guard that names the owner of an unexpectedly dirty main checkout.

Both the CLI entrypoint and the workbench backend boot path need the same
report, so the inspection, the attribution rendering and the block switch live
here once and each startup surface only calls ``report_dirty_main_worktree``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MAIN_GUARD_BLOCK_ENV = "VIBELUTION_MAIN_GUARD"

_BLOCK_VALUE = "block"


def dirty_main_worktree_detail(payload: dict) -> str:
    """Render one bounded, owner-naming report body from a main_guard payload."""

    file_lines = [str(line) for line in payload.get("fileLines") or []]
    owners = [str(owner) for owner in payload.get("owners") or []]
    return "\n".join(
        [
            f"main 工作区有未提交改动（{len(file_lines)} 处）",
            *file_lines,
            *(f"dirty_main_suspected_owner: {owner}" for owner in owners),
            f"处理建议: {payload.get('nextAction') or '先让所属会话提交或撤销这些改动。'}",
        ]
    )


def report_dirty_main_worktree(root: Path | str, *, surface: str = "startup") -> bool:
    """Report a dirty shared main checkout; return whether anything was reported.

    ``scripts/task_closeout.py`` already refuses to merge while the shared main
    checkout holds uncommitted edits, but it only speaks after a task is
    finished: by then every other task is blocked and nobody knows whom to ask.
    Reporting the same attribution at startup makes the owner visible early.

    The default is a warning, not a failure. A checkout is often dirty during a
    merge, and refusing startup would keep every session out of the project --
    strictly worse than the block this check exists to explain. Set
    ``VIBELUTION_MAIN_GUARD=block`` to turn it into a refusal.

    Every inspection failure collapses to "nothing to report": a packaged build
    has no git checkout, and a coordination outage must never become a startup
    failure.
    """

    try:
        from scripts import main_guard

        payload = main_guard.inspect_main_checkout(Path(root))
    except (OSError, RuntimeError, ValueError, ImportError):
        return False
    if payload.get("status") == "clean":
        return False
    detail = dirty_main_worktree_detail(payload)
    if os.environ.get(MAIN_GUARD_BLOCK_ENV, "").strip().lower() == _BLOCK_VALUE:
        raise RuntimeError(f"main 工作区不干净，已阻止启动:\n{detail}")
    print(f"[{surface}] {detail}", file=sys.stderr)
    return True
