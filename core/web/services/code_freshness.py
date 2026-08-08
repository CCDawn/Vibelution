"""Running-code freshness detection.

The workbench backend snapshots the git commit it was started from
(``.runtime/running-code-fingerprint.json``). ``resolve_code_freshness``
compares that snapshot with the current disk HEAD so the UI can tell the
user the running instance is behind the repository and a restart is needed.

Git calls go through ``core.infrastructure.no_console_git`` (CREATE_NO_WINDOW +
GIT_OPTIONAL_LOCKS=0), matching the Windows no-console red line and the
GitHub-Desktop convention of not competing with user git operations.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.no_console_git import run_git

FINGERPRINT_SCHEMA_VERSION = 1
FINGERPRINT_RELATIVE = Path(".runtime") / "running-code-fingerprint.json"
FRONTEND_BUILD_PROVENANCE_RELATIVE = Path("web") / "dist" / ".vibelution-build.json"
GIT_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_git_text(project_root: Path | str, args: list[str]) -> str:
    try:
        result = run_git(args, cwd=str(project_root), timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return ""
    if int(result.returncode or 0) != 0:
        return ""
    return str(result.stdout or "").strip()


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def running_code_fingerprint_path(project_root: Path | str) -> Path:
    return Path(project_root) / FINGERPRINT_RELATIVE


def frontend_build_provenance_path(project_root: Path | str) -> Path:
    return Path(project_root) / FRONTEND_BUILD_PROVENANCE_RELATIVE


def write_running_code_fingerprint(
    *,
    project_root: Path | str,
    source: str = "web_workbench_lifespan",
) -> dict[str, Any]:
    """Snapshot the git commit this backend process was started from.

    Best effort: a failed write must never block or crash startup, so the
    payload reports ``written`` and callers treat a missing snapshot as
    ``unknown`` freshness rather than an error.
    """
    root = Path(project_root)
    head = _capture_git_text(root, ["rev-parse", "HEAD"])
    branch = _capture_git_text(root, ["branch", "--show-current"])
    payload: dict[str, Any] = {
        "schemaVersion": FINGERPRINT_SCHEMA_VERSION,
        "projectRoot": str(root.resolve()),
        "runningHead": head,
        "runningBranch": branch,
        "startedAt": _now_iso(),
        "source": source,
    }
    path = running_code_fingerprint_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
        payload["written"] = True
        payload["path"] = str(path)
    except OSError as exc:
        payload["written"] = False
        payload["errorType"] = type(exc).__name__
        payload["errorMessage"] = str(exc)
    return payload


def read_running_code_fingerprint(project_root: Path | str) -> dict[str, Any] | None:
    path = running_code_fingerprint_path(project_root)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(parsed, dict) or int(parsed.get("schemaVersion") or 0) != FINGERPRINT_SCHEMA_VERSION:
        return None
    return parsed


def read_frontend_build_provenance(project_root: Path | str) -> dict[str, Any] | None:
    """Return the dist provenance stamped by the runtime-manager build preflight."""
    path = frontend_build_provenance_path(project_root)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_behind_count(value: str) -> int | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed >= 0 else None


def resolve_backend_freshness(
    *,
    project_root: Path | str,
) -> dict[str, Any]:
    """Compare the running snapshot with the current disk HEAD.

    Pure decision inputs keep this function unit-testable; git reads are the
    only side effect and they never lock (GIT_OPTIONAL_LOCKS=0).
    """
    root = Path(project_root)
    running = read_running_code_fingerprint(root)
    disk_head = _capture_git_text(root, ["rev-parse", "HEAD"])
    disk_branch = _capture_git_text(root, ["branch", "--show-current"])

    running_head = str((running or {}).get("runningHead") or "").strip()
    if not running_head:
        return {
            "available": False,
            "reason": "no_running_fingerprint",
            "running": None,
            "disk": {"head": disk_head, "branch": disk_branch},
        }
    if not disk_head:
        return {
            "available": False,
            "reason": "git_unavailable",
            "running": {
                "head": running_head,
                "branch": str((running or {}).get("runningBranch") or "").strip(),
                "startedAt": str((running or {}).get("startedAt") or "").strip(),
            },
            "disk": {"head": "", "branch": ""},
        }

    behind_count: int | None = None
    if running_head != disk_head:
        behind_count = _parse_behind_count(
            _capture_git_text(root, ["rev-list", "--count", f"{running_head}..{disk_head}"])
        )
    return {
        "available": True,
        "reason": "",
        "behind": running_head != disk_head,
        "behindCount": behind_count,
        "running": {
            "head": running_head,
            "branch": str((running or {}).get("runningBranch") or "").strip(),
            "startedAt": str((running or {}).get("startedAt") or "").strip(),
        },
        "disk": {"head": disk_head, "branch": disk_branch},
    }


def resolve_frontend_freshness(
    *,
    project_root: Path | str,
) -> dict[str, Any]:
    """Compare the dist build provenance with the current ``HEAD:web`` tree.

    Mirrors the runtime-manager preflight semantics: a dist that was built from
    an older tree is stale even when the running backend is current.
    """
    root = Path(project_root)
    provenance = read_frontend_build_provenance(root)
    if not provenance:
        return {
            "available": False,
            "reason": "no_provenance",
            "builtFromCommit": "",
            "frontendTree": "",
        }
    built_from = str(provenance.get("builtFromCommit") or "").strip()
    frontend_tree = str(provenance.get("frontendTree") or "").strip()
    disk_tree = _capture_git_text(root, ["rev-parse", "HEAD:web"])
    if not disk_tree:
        return {
            "available": False,
            "reason": "git_unavailable",
            "builtFromCommit": built_from,
            "frontendTree": frontend_tree,
        }
    return {
        "available": True,
        "reason": "",
        "stale": bool(frontend_tree and frontend_tree != disk_tree),
        "builtFromCommit": built_from,
        "frontendTree": frontend_tree,
    }


def resolve_code_freshness(*, project_root: Path | str) -> dict[str, Any]:
    """Combine backend + frontend freshness into one verdict for the UI."""
    backend = resolve_backend_freshness(project_root=project_root)
    frontend = resolve_frontend_freshness(project_root=project_root)

    backend_behind = bool(backend.get("behind"))
    frontend_stale = bool(frontend.get("stale"))
    backend_available = bool(backend.get("available"))
    frontend_available = bool(frontend.get("available"))

    if not backend_available or not frontend_available:
        verdict = "unknown"
    elif backend_behind and frontend_stale:
        verdict = "backend_and_frontend_behind"
    elif backend_behind:
        verdict = "backend_behind"
    elif frontend_stale:
        verdict = "frontend_behind"
    else:
        verdict = "current"

    return {
        "schemaVersion": FINGERPRINT_SCHEMA_VERSION,
        "verdict": verdict,
        "backend": {
            "available": backend_available,
            "behind": backend_behind,
            "behindCount": backend.get("behindCount"),
            "reason": backend.get("reason") or "",
            "running": backend.get("running"),
            "disk": backend.get("disk"),
        },
        "frontend": {
            "available": frontend_available,
            "stale": frontend_stale,
            "reason": frontend.get("reason") or "",
            "builtFromCommit": _short_sha(str(frontend.get("builtFromCommit") or "")),
            "frontendTree": str(frontend.get("frontendTree") or ""),
        },
    }
