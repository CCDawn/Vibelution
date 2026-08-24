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

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure.no_console_git import run_git
from core.runtime_manager.process_identity import capture_process_identity

FINGERPRINT_SCHEMA_VERSION = 1
FINGERPRINT_RELATIVE = Path(".runtime") / "running-code-fingerprint.json"
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


def _dirty_tree_summary(project_root: Path | str) -> dict[str, Any]:
    raw = _capture_git_text(project_root, ["status", "--porcelain=v1", "--untracked-files=all"])
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return {
        "dirty": bool(normalized),
        "dirtyTreeDigest": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""


def running_code_fingerprint_path(project_root: Path | str) -> Path:
    return Path(project_root) / FINGERPRINT_RELATIVE


def frontend_build_provenance_path(project_root: Path | str) -> Path:
    from core.launcher.frontend_build import resolve_active_frontend_dist

    return resolve_active_frontend_dist(project_root) / ".vibelution-build.json"


def write_running_code_fingerprint(
    *,
    project_root: Path | str,
    source: str = "web_workbench_lifespan",
    serving_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot the git commit this backend process was started from.

    Best effort: a failed write must never block or crash startup, so the
    payload reports ``written`` and callers treat a missing snapshot as
    ``unknown`` freshness rather than an error.
    """
    root = Path(project_root)
    head = _capture_git_text(root, ["rev-parse", "HEAD"])
    branch = _capture_git_text(root, ["branch", "--show-current"])
    dirty = _dirty_tree_summary(root)
    identity = capture_process_identity(os.getpid())
    frontend_value = serving_metadata.get("frontend") if isinstance(serving_metadata, dict) else {}
    backend_value = serving_metadata.get("backend") if isinstance(serving_metadata, dict) else {}
    frontend = frontend_value if isinstance(frontend_value, dict) else {}
    backend = backend_value if isinstance(backend_value, dict) else {}
    started_at = str((backend or {}).get("startedAt") or _now_iso())
    payload: dict[str, Any] = {
        "schemaVersion": FINGERPRINT_SCHEMA_VERSION,
        "projectRoot": str(root.resolve()),
        "runningHead": head,
        "runningBranch": branch,
        "dirty": bool(dirty["dirty"]),
        "dirtyTreeDigest": str(dirty["dirtyTreeDigest"]),
        "pid": int(os.getpid()),
        "createTime": identity.get("createTime") or (backend or {}).get("createTime"),
        "executable": str(identity.get("executable") or (backend or {}).get("executable") or ""),
        "startedAt": started_at,
        "source": source,
    }
    if isinstance(serving_metadata, dict) and isinstance(frontend_value, dict):
        payload.update(
            {
                "servingFrontendBuildKey": str(frontend.get("buildKey") or ""),
                "servingFrontendRelease": str(frontend.get("release") or ""),
                "servingFrontendDist": str(frontend.get("dist") or ""),
                "servingFrontendBuiltFromCommit": str(frontend.get("builtFromCommit") or ""),
            }
        )
    if isinstance(serving_metadata, dict):
        payload["apiContractVersion"] = str(serving_metadata.get("apiContractVersion") or "v1")
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
    """Return provenance from the atomically activated frontend release."""
    from core.launcher.frontend_build import read_active_provenance

    parsed = read_active_provenance(project_root)
    return parsed if parsed else None


def _inspect_active_frontend_build(project_root: Path | str) -> dict[str, Any]:
    from core.launcher.frontend_build import inspect_frontend_build

    return inspect_frontend_build(project_root)


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
    disk_dirty = _dirty_tree_summary(root)

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
            "disk": {"head": "", "branch": "", **disk_dirty},
        }

    behind_count: int | None = None
    running_dirty_digest = str((running or {}).get("dirtyTreeDigest") or "").strip()
    dirty_differs = bool(running_dirty_digest) and running_dirty_digest != str(disk_dirty["dirtyTreeDigest"])
    if running_head != disk_head:
        behind_count = _parse_behind_count(
            _capture_git_text(root, ["rev-list", "--count", f"{running_head}..{disk_head}"])
        )
    if not running_dirty_digest:
        return {
            "available": False,
            "reason": "running_fingerprint_missing_dirty_digest",
            "running": {
                "head": running_head,
                "branch": str((running or {}).get("runningBranch") or "").strip(),
                "startedAt": str((running or {}).get("startedAt") or "").strip(),
                "pid": int((running or {}).get("pid") or 0),
            },
            "disk": {"head": disk_head, "branch": disk_branch, **disk_dirty},
        }
    return {
        "available": True,
        "reason": "",
        "behind": running_head != disk_head or dirty_differs,
        "behindCount": behind_count,
        "running": {
            "head": running_head,
            "branch": str((running or {}).get("runningBranch") or "").strip(),
            "startedAt": str((running or {}).get("startedAt") or "").strip(),
            "dirty": bool((running or {}).get("dirty")),
            "dirtyTreeDigest": running_dirty_digest,
            "pid": int((running or {}).get("pid") or 0),
            "createTime": (running or {}).get("createTime"),
            "executable": str((running or {}).get("executable") or ""),
        },
        "disk": {"head": disk_head, "branch": disk_branch, **disk_dirty},
    }


def resolve_frontend_freshness(*, project_root: Path | str) -> dict[str, Any]:
    """Compare the active release with the exact inputs that determine its bytes."""
    root = Path(project_root)
    try:
        inspection = _inspect_active_frontend_build(root)
    except OSError:
        inspection = {}
    provenance = inspection.get("provenance") if isinstance(inspection.get("provenance"), dict) else {}
    if not provenance:
        return {
            "available": False,
            "reason": "no_provenance",
            "builtFromCommit": "",
            "frontendTree": "",
            "buildKey": "",
        }
    built_from = str(provenance.get("builtFromCommit") or "").strip()
    frontend_tree = str(provenance.get("frontendTree") or "").strip()
    active_build_key = str(provenance.get("buildKey") or "").strip()
    running = read_running_code_fingerprint(root) or {}
    serving_build_key = str(running.get("servingFrontendBuildKey") or "").strip()
    serving_release = str(running.get("servingFrontendRelease") or "").strip()
    active_release = ""
    try:
        from core.launcher.frontend_build import active_release_path

        pointer = json.loads(active_release_path(root).read_text(encoding="utf-8"))
        if isinstance(pointer, dict):
            active_release = str(pointer.get("release") or "").strip()
    except (OSError, ValueError, TypeError):
        active_release = ""
    serving_metadata_present = "servingFrontendBuildKey" in running
    serving_mismatch = serving_metadata_present and (
        not serving_build_key
        or serving_build_key != active_build_key
        or (serving_release and active_release and serving_release != active_release)
    )
    return {
        "available": True,
        "reason": "serving release differs from active release" if serving_mismatch else str(inspection.get("reason") or ""),
        "stale": not bool(inspection.get("current")) or serving_mismatch,
        "builtFromCommit": built_from,
        "frontendTree": frontend_tree,
        "buildKey": active_build_key,
        "servingBuildKey": serving_build_key,
        "servingRelease": serving_release,
        "activeRelease": active_release,
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
            "buildKey": _short_sha(str(frontend.get("buildKey") or "")),
            "servingBuildKey": _short_sha(str(frontend.get("servingBuildKey") or "")),
            "servingRelease": str(frontend.get("servingRelease") or ""),
            "activeRelease": str(frontend.get("activeRelease") or ""),
        },
    }
