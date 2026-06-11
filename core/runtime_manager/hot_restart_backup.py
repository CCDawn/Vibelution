"""Hot-restart backup, failure capture, and rollback helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import PROJECT_ROOT, RUNTIME_MANAGER_DIR, ensure_runtime_manager_dirs
from .scene_logging import truncate_event_text


HOT_RESTART_DIR = RUNTIME_MANAGER_DIR / "hot-restart"
STABLE_BACKUPS_DIR = HOT_RESTART_DIR / "stable-backups"
FAILURE_PACKAGES_DIR = HOT_RESTART_DIR / "failure-packages"
MAX_STABLE_BACKUPS = 3

BACKUP_TARGETS: tuple[str, ...] = (
    "agent.py",
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTEXT.md",
    "README.md",
    "VERSION",
    "config",
    "core",
    "scripts",
    "tests",
    "tools",
    "web/src",
    "web/dist",
    "web/package.json",
    "web/package-lock.json",
    "web/tsconfig.app.json",
    "web/vite.config.ts",
)

EXCLUDED_PATH_PARTS = {
    ".git",
    ".runtime",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "logs",
    "log_info",
    "workspace",
    "backups",
    "tmp",
}

SENSITIVE_TEXT_MARKERS = (
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "secret",
    "token",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"


def _safe_relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _is_excluded(relative_path: str) -> bool:
    parts = set(Path(relative_path).parts)
    return bool(parts & EXCLUDED_PATH_PARTS)


def _iter_backup_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for target in BACKUP_TARGETS:
        path = (PROJECT_ROOT / target).resolve()
        if not path.exists():
            continue
        if path.is_file():
            rel = _safe_relative(path)
            if not _is_excluded(rel) and rel not in seen:
                files.append((path, rel))
                seen.add(rel)
            continue
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            rel = _safe_relative(child)
            if _is_excluded(rel) or rel in seen:
                continue
            files.append((child, rel))
            seen.add(rel)
    return files


def _run_git(args: list[str], *, timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return result.stdout.strip()


def _redact_sensitive_text(text: str) -> str:
    redacted_lines: list[str] = []
    for line in str(text or "").splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in SENSITIVE_TEXT_MARKERS):
            redacted_lines.append("[REDACTED sensitive line]")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _git_metadata() -> dict[str, Any]:
    return {
        "branch": _run_git(["branch", "--show-current"]),
        "head": _run_git(["rev-parse", "HEAD"]),
        "statusShort": _run_git(["status", "--short"]),
    }


def ensure_hot_restart_dirs() -> None:
    ensure_runtime_manager_dirs()
    for path in (HOT_RESTART_DIR, STABLE_BACKUPS_DIR, FAILURE_PACKAGES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def create_stable_backup(*, reason: str, command_id: str = "", runtime_scene_id: str = "") -> dict[str, Any]:
    """Create a rollback-capable source snapshot after a verified healthy startup."""

    ensure_hot_restart_dirs()
    backup_id = _backup_id("stable")
    backup_dir = STABLE_BACKUPS_DIR / backup_id
    backup_dir.mkdir(parents=True, exist_ok=False)
    archive_path = backup_dir / "snapshot.zip"
    files = _iter_backup_files()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, rel in files:
            archive.write(path, rel)
    manifest = {
        "backupId": backup_id,
        "kind": "stable",
        "status": "available",
        "createdAt": _now_iso(),
        "reason": str(reason or "").strip(),
        "commandId": str(command_id or "").strip(),
        "runtimeSceneId": str(runtime_scene_id or "").strip(),
        "archivePath": str(archive_path),
        "fileCount": len(files),
        "targets": list(BACKUP_TARGETS),
        "excludedPathParts": sorted(EXCLUDED_PATH_PARTS),
        "git": _git_metadata(),
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    pruned = prune_stable_backups(max_count=MAX_STABLE_BACKUPS)
    manifest["prunedBackupIds"] = pruned
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def list_stable_backups() -> list[dict[str, Any]]:
    ensure_hot_restart_dirs()
    backups: list[dict[str, Any]] = []
    for manifest_path in sorted(STABLE_BACKUPS_DIR.glob("*/manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and str(payload.get("status") or "") == "available":
            backups.append(payload)
    backups.sort(key=lambda item: str(item.get("createdAt") or ""))
    return backups


def latest_stable_backup() -> dict[str, Any]:
    backups = list_stable_backups()
    return backups[-1] if backups else {}


def prune_stable_backups(*, max_count: int = MAX_STABLE_BACKUPS) -> list[str]:
    backups = list_stable_backups()
    excess = max(0, len(backups) - max(1, int(max_count or MAX_STABLE_BACKUPS)))
    pruned: list[str] = []
    for item in backups[:excess]:
        backup_id = str(item.get("backupId") or "").strip()
        if not backup_id:
            continue
        path = STABLE_BACKUPS_DIR / backup_id
        try:
            shutil.rmtree(path)
            pruned.append(backup_id)
        except OSError:
            continue
    return pruned


def _changed_paths_from_git_status(status_text: str) -> list[str]:
    paths: list[str] = []
    for line in status_text.splitlines():
        if not line.strip():
            continue
        raw = line[3:] if len(line) > 3 else line
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        normalized = raw.strip().strip('"').replace("\\", "/")
        if normalized and not _is_excluded(normalized):
            paths.append(normalized)
    return sorted(set(paths))


def create_failure_package(
    *,
    reason: str,
    command_id: str = "",
    session_id: str = "",
    run_id: str = "",
    intent_id: str = "",
    failure_stage: str = "",
    error_type: str = "",
    error_message: str = "",
    runtime_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a diagnostic package for failed hot restart attempts."""

    ensure_hot_restart_dirs()
    package_id = _backup_id("failure")
    package_dir = FAILURE_PACKAGES_DIR / package_id
    package_dir.mkdir(parents=True, exist_ok=False)

    status_text = _run_git(["status", "--short"], timeout=12.0)
    diff_text = _redact_sensitive_text(_run_git(["diff", "--binary"], timeout=20.0))
    changed_paths = _changed_paths_from_git_status(status_text)
    (package_dir / "git_status.txt").write_text(status_text, encoding="utf-8")
    (package_dir / "git_diff.patch").write_text(diff_text, encoding="utf-8")

    changed_archive_path = package_dir / "changed-files.zip"
    archived_files: list[str] = []
    with zipfile.ZipFile(changed_archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative_path in changed_paths:
            path = (PROJECT_ROOT / relative_path).resolve()
            if not path.exists() or not path.is_file():
                continue
            try:
                path.relative_to(PROJECT_ROOT.resolve())
            except ValueError:
                continue
            archive.write(path, relative_path)
            archived_files.append(relative_path)

    manifest = {
        "packageId": package_id,
        "kind": "hot_restart_failure",
        "createdAt": _now_iso(),
        "reason": str(reason or "").strip(),
        "commandId": str(command_id or "").strip(),
        "sessionId": str(session_id or "").strip(),
        "runId": str(run_id or "").strip(),
        "intentId": str(intent_id or "").strip(),
        "failureStage": str(failure_stage or "").strip(),
        "errorType": str(error_type or "").strip(),
        "errorMessage": truncate_event_text(str(error_message or ""), limit=1000),
        "gitStatusPath": str(package_dir / "git_status.txt"),
        "gitDiffPath": str(package_dir / "git_diff.patch"),
        "changedFilesArchivePath": str(changed_archive_path),
        "changedFiles": changed_paths,
        "archivedFiles": archived_files,
        "runtimeResult": runtime_result or {},
        "redaction": {
            "strategy": "line_redaction",
            "markers": list(SENSITIVE_TEXT_MARKERS),
            "appliesTo": ["git_diff.patch", "manifest.errorMessage"],
        },
        "git": _git_metadata(),
    }
    (package_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def restore_stable_backup(backup: dict[str, Any] | None = None) -> dict[str, Any]:
    """Restore code/build files from the latest stable backup."""

    selected = backup if isinstance(backup, dict) and backup else latest_stable_backup()
    backup_id = str(selected.get("backupId") or "").strip()
    archive_path = Path(str(selected.get("archivePath") or ""))
    if not backup_id or not archive_path.exists():
        raise RuntimeError("No stable hot-restart backup is available for rollback.")

    with tempfile.TemporaryDirectory(prefix="hot-restart-restore-") as temp_dir:
        extract_root = Path(temp_dir)
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(extract_root)

        for target in BACKUP_TARGETS:
            relative_target = Path(target)
            if _is_excluded(relative_target.as_posix()):
                continue
            destination = (PROJECT_ROOT / relative_target).resolve()
            source = (extract_root / relative_target).resolve()
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            if not source.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

    return {
        "backupId": backup_id,
        "restoredAt": _now_iso(),
        "archivePath": str(archive_path),
        "targets": list(BACKUP_TARGETS),
    }


__all__ = [
    "BACKUP_TARGETS",
    "FAILURE_PACKAGES_DIR",
    "HOT_RESTART_DIR",
    "MAX_STABLE_BACKUPS",
    "STABLE_BACKUPS_DIR",
    "create_failure_package",
    "create_stable_backup",
    "ensure_hot_restart_dirs",
    "latest_stable_backup",
    "list_stable_backups",
    "prune_stable_backups",
    "restore_stable_backup",
]
