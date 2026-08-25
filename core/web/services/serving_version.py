"""Runtime serving-version metadata shared by health and freshness surfaces.

The frontend release pointer is mutable, while a running process must keep
serving the immutable release it mounted at startup.  This module captures
that distinction once and exposes only bounded provenance/identity fields to
the launcher.  It deliberately does not expose raw ``git status`` output.
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

API_CONTRACT_VERSION = "v1"
SERVING_VERSION_SCHEMA_VERSION = 1
GIT_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_text(project_root: Path, args: list[str]) -> str:
    try:
        result = run_git(args, cwd=str(project_root), timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return ""
    if int(result.returncode or 0) != 0:
        return ""
    return str(result.stdout or "")


def git_dirty_tree_summary(project_root: Path | str) -> dict[str, Any]:
    """Return a stable, privacy-preserving summary of the working tree."""

    root = Path(project_root).resolve()
    raw = _git_text(root, ["status", "--porcelain=v1", "--untracked-files=all"])
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return {
        "dirty": bool(normalized),
        "dirtyTreeDigest": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def resolve_serving_frontend(project_root: Path | str) -> dict[str, Any]:
    """Capture the immutable frontend release selected for this process."""

    from core.launcher.frontend_build import (
        active_release_path,
        frontend_releases_dir,
        resolve_active_frontend_dist,
    )

    root = Path(project_root).resolve()
    dist = resolve_active_frontend_dist(root).resolve()
    try:
        provenance = json.loads((dist / ".vibelution-build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        provenance = {}
    if not isinstance(provenance, dict):
        provenance = {}

    release = ""
    try:
        pointer = json.loads(active_release_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pointer = {}
    if isinstance(pointer, dict):
        candidate = str(pointer.get("release") or "").strip()
        releases = frontend_releases_dir(root).resolve()
        if candidate and Path(candidate).name == candidate and candidate.startswith("release-"):
            release_path = (releases / candidate).resolve()
            try:
                if release_path.is_relative_to(releases) and release_path == dist:
                    release = candidate
            except OSError:
                release = ""

    return {
        "schemaVersion": SERVING_VERSION_SCHEMA_VERSION,
        "buildKey": str(provenance.get("buildKey") or "").strip(),
        "release": release,
        "dist": str(dist),
        "builtFromCommit": str(provenance.get("builtFromCommit") or provenance.get("sourceCommit") or "").strip(),
    }


def build_backend_code_fingerprint(
    project_root: Path | str,
    *,
    pid: int | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Return code + process identity for the currently running backend."""

    root = Path(project_root).resolve()
    normalized_pid = int(pid if pid is not None else os.getpid())
    identity = capture_process_identity(normalized_pid)
    dirty = git_dirty_tree_summary(root)
    return {
        "schemaVersion": SERVING_VERSION_SCHEMA_VERSION,
        "head": _git_text(root, ["rev-parse", "HEAD"]).strip(),
        "dirty": bool(dirty["dirty"]),
        "dirtyTreeDigest": str(dirty["dirtyTreeDigest"]),
        "pid": normalized_pid,
        "createTime": identity.get("createTime"),
        "executable": str(identity.get("executable") or ""),
        "startedAt": str(started_at or _now_iso()),
    }


def build_serving_metadata(
    project_root: Path | str,
    *,
    pid: int | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Build the health payload's stable serving contract."""

    root = Path(project_root).resolve()
    backend = build_backend_code_fingerprint(root, pid=pid, started_at=started_at)
    frontend = resolve_serving_frontend(root)
    return {
        "schemaVersion": SERVING_VERSION_SCHEMA_VERSION,
        "apiContractVersion": API_CONTRACT_VERSION,
        "frontend": frontend,
        "backend": backend,
    }


__all__ = [
    "API_CONTRACT_VERSION",
    "SERVING_VERSION_SCHEMA_VERSION",
    "build_backend_code_fingerprint",
    "build_serving_metadata",
    "git_dirty_tree_summary",
    "resolve_serving_frontend",
]
