"""Clear legacy chat and CLI Agent runtime state after the turn journal migration.

This script is intentionally explicit and destructive only with --confirm-delete.
It keeps project source files intact and removes only product runtime state.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.ui.chat_state import build_chat_state, chat_state_path, save_chat_state


def clear_chat_journal_state(project_root: Path, *, confirm_delete: bool) -> dict[str, Any]:
    root = Path(project_root).resolve()
    targets = _cleanup_targets(root)
    result: dict[str, Any] = {
        "status": "preview" if not confirm_delete else "cleared",
        "projectRoot": str(root),
        "confirmed": bool(confirm_delete),
        "chatStatePath": str(chat_state_path(root)),
        "targets": [str(path) for path in targets],
        "deleted": [],
        "skipped": [],
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    if not confirm_delete:
        return result

    save_chat_state(root, build_chat_state([]))
    for target in targets:
        safe_target = _safe_runtime_target(root, target)
        if not safe_target.exists():
            result["skipped"].append(str(safe_target))
            continue
        if safe_target.is_dir():
            shutil.rmtree(safe_target)
        else:
            safe_target.unlink()
        result["deleted"].append(str(safe_target))
    return result


def _cleanup_targets(project_root: Path) -> list[Path]:
    workspace_sessions = developer_sandbox.sandboxed_workspace_path(project_root, "sessions")
    formal_sessions = developer_sandbox.formal_workspace_path(project_root, "sessions")
    runtime_root = project_root / ".runtime" / "cli_agents"
    raw_targets = [
        workspace_sessions,
        formal_sessions,
        runtime_root / "sessions",
        runtime_root / "tasks",
        runtime_root / "transcripts",
        runtime_root / "runs",
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for path in raw_targets:
        resolved = path.resolve()
        token = str(resolved).lower()
        if token in seen:
            continue
        seen.add(token)
        result.append(resolved)
    return result


def _safe_runtime_target(project_root: Path, target: Path) -> Path:
    resolved_root = project_root.resolve()
    resolved = target.resolve()
    allowed_roots = [
        resolved_root / "workspace",
        resolved_root / ".runtime" / "cli_agents",
        resolved_root / ".runtime" / "developer-mode" / "sandboxes",
    ]
    if any(_is_relative_to(resolved, allowed.resolve()) for allowed in allowed_roots):
        return resolved
    raise ValueError(f"Refusing to delete path outside runtime state: {resolved}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear legacy chat journal and CLI Agent runtime state.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Vibelution project root.")
    parser.add_argument("--confirm-delete", action="store_true", help="Actually delete runtime state.")
    args = parser.parse_args()
    payload = clear_chat_journal_state(Path(args.project_root), confirm_delete=bool(args.confirm_delete))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
