"""Compare this Launcher process to the current local Git HEAD."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import git_process
from core.runtime_manager.constants import PROJECT_ROOT

_started: dict[str, str] | None = None


def capture_launcher_start_identity() -> dict[str, str]:
    """Record the Git identity of this process once, at startup.

    An empty first capture (git unavailable) must not freeze the process as
    unknown forever; retry until a commit is known.
    """

    global _started
    if _started is not None and str(_started.get("commit") or "").strip():
        return dict(_started)
    identity = _git_identity()
    identity["startedAt"] = str((_started or {}).get("startedAt") or "") or _now_iso()
    _started = identity
    return dict(_started)


def reset_launcher_start_identity_for_tests() -> None:
    global _started
    _started = None


def get_launcher_freshness() -> dict[str, Any]:
    started = capture_launcher_start_identity()
    head = _git_identity()
    running_commit = started.get("commit") or ""
    head_commit = head.get("commit") or ""
    known = bool(running_commit and head_commit)
    current = known and running_commit == head_commit
    running_short = _short_sha(running_commit)
    head_short = _short_sha(head_commit)
    if not known:
        label = "Launcher 版本未知"
    elif current:
        label = f"Launcher 已是最新 · {running_short}"
    else:
        label = f"Launcher 落后本地 main · {running_short} → {head_short}"
    shell_stale, shell_reason = _unpackaged_shell_update()
    update_available = (current is False) or shell_stale
    return {
        "schemaVersion": 1,
        "current": current if known else None,
        "label": label,
        "runningCommit": running_commit,
        "runningShort": running_short,
        "runningBranch": started.get("branch") or "",
        "headCommit": head_commit,
        "headShort": head_short,
        "headBranch": head.get("branch") or "",
        "startedAt": started.get("startedAt") or "",
        "shellStale": shell_stale,
        "shellReason": shell_reason,
        "updateAvailable": update_available,
    }


def _git_identity() -> dict[str, str]:
    try:
        commit = git_process.run_git(
            ["rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        branch = git_process.run_git(
            ["branch", "--show-current"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if int(commit.returncode or 0) != 0:
            return {"commit": "", "branch": ""}
        return {
            "commit": str(commit.stdout or "").strip(),
            "branch": str(branch.stdout or "").strip() or "HEAD",
        }
    except (OSError, TypeError, ValueError):
        return {"commit": "", "branch": ""}


def _unpackaged_shell_update() -> tuple[bool, str]:
    """Report whether the checkout Electron bundle is behind the current sources.

    A missing Electron binary is an environment gap, not a version the user can
    restart into. Inspection failure must not turn a freshness read into a prompt.
    """

    try:
        from core.launcher.desktop_shell import (
            inspect_unpackaged_electron,
            unpackaged_electron_executable,
        )
        from core.launcher.desktop_shell_owner import read_desktop_shell_owner

        status = inspect_unpackaged_electron(PROJECT_ROOT)
        reason = str(status.get("reason") or "")
        if reason == "missing_binary" or not status.get("stale"):
            return False, reason
        owner = read_desktop_shell_owner(PROJECT_ROOT) or {}
        electron_bin = unpackaged_electron_executable(PROJECT_ROOT)
        owner_exe = str(owner.get("executable") or "").strip()
        if electron_bin is None or not owner_exe:
            return False, reason
        if Path(owner_exe).resolve() != electron_bin.resolve():
            return False, reason
        return True, reason
    except (OSError, RuntimeError, ValueError, TypeError, ImportError):
        return False, ""


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
