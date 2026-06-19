"""Workspace data migration and legacy workspace cleanup operations."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from config.paths import resolve_data_backup_dir, resolve_workspace_home

from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_MANIFEST_NAME = "workspace_manifest.json"
LEGACY_WORKSPACE_CLEANUP_CONFIRMATION = "硬删除旧 workspace"
DEFAULT_TOP_LEVEL_EXCLUDES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    WORKSPACE_MANIFEST_NAME,
}


class WorkspaceDataMigrationError(ValueError):
    """Raised when workspace migration or legacy cleanup is not allowed."""


def get_workspace_migration_status(
    *,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    source_workspace = _source_workspace(root)
    target_workspace = resolve_workspace_home(data_home, config_path=config_path)
    exclusion_set = _normalize_excludes(excludes)
    verification = verify_workspace_migration(
        project_root=root,
        data_home=data_home,
        config_path=config_path,
        excludes=exclusion_set,
        include_report=False,
    )
    cleanup_blockers = _legacy_cleanup_blockers(
        project_root=root,
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        verification=verification,
    )
    manifest_path = target_workspace / WORKSPACE_MANIFEST_NAME
    return {
        "schemaVersion": 1,
        "mode": "external_workspace_migration_status",
        "generatedAt": _now_iso(),
        "projectRoot": str(root),
        "sourceWorkspace": str(source_workspace),
        "targetWorkspace": str(target_workspace),
        "manifestPath": str(manifest_path),
        "source": _path_summary(source_workspace),
        "target": _path_summary(target_workspace),
        "samePath": _same_path(source_workspace, target_workspace),
        "sourceExists": source_workspace.exists(),
        "targetExists": target_workspace.exists(),
        "migrationNeeded": source_workspace.exists() and not _same_path(source_workspace, target_workspace),
        "verification": verification,
        "legacyCleanup": {
            "confirmationPhrase": LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
            "canPreview": source_workspace.exists() and not _same_path(source_workspace, target_workspace),
            "canExecute": not cleanup_blockers,
            "blockedReasons": cleanup_blockers,
        },
        "manifest": _read_manifest(manifest_path),
    }


def preview_workspace_migration(
    *,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    target_workspace = resolve_workspace_home(data_home, config_path=config_path)
    return build_report(
        action="preview",
        source_workspace=_source_workspace(root),
        target_workspace=target_workspace,
        excludes=_normalize_excludes(excludes),
    )


def apply_workspace_migration(
    *,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    target_workspace = resolve_workspace_home(data_home, config_path=config_path)
    report = build_report(
        action="apply",
        source_workspace=_source_workspace(root),
        target_workspace=target_workspace,
        excludes=_normalize_excludes(excludes),
    )
    apply_migration(report, data_home=data_home, config_path=config_path)
    report = build_report(
        action="apply",
        source_workspace=_source_workspace(root),
        target_workspace=target_workspace,
        excludes=_normalize_excludes(excludes),
    )
    report["applied"] = True
    report["verified"] = verify_migration(report)
    report["manifest"] = write_workspace_manifest(target_workspace, excludes=_normalize_excludes(excludes))
    _write_report(report_path, report)
    _record_workspace_event(
        "migration",
        "workspace_data_migration.applied",
        outcome="succeeded",
        fields={
            "sourceWorkspace": str(report.get("sourceWorkspace") or ""),
            "targetWorkspace": str(report.get("targetWorkspace") or ""),
            "itemCount": int((report.get("totals") or {}).get("itemCount") or 0),
            "verified": bool((report.get("verified") or {}).get("ok")),
        },
    )
    return report


def verify_workspace_migration(
    *,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
    include_report: bool = True,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    report = build_report(
        action="verify",
        source_workspace=_source_workspace(root),
        target_workspace=resolve_workspace_home(data_home, config_path=config_path),
        excludes=_normalize_excludes(excludes),
    )
    verified = verify_migration(report)
    if verified["ok"] and report["targetExists"]:
        verified["manifest"] = write_workspace_manifest(Path(report["targetWorkspace"]), excludes=_normalize_excludes(excludes))
    if include_report:
        report["verified"] = verified
        _write_report(report_path, report)
        return report
    return verified


def preview_legacy_workspace_cleanup(
    *,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    source_workspace = _source_workspace(root)
    target_workspace = resolve_workspace_home(data_home, config_path=config_path)
    verification = verify_workspace_migration(
        project_root=root,
        data_home=data_home,
        config_path=config_path,
        excludes=_normalize_excludes(excludes),
        include_report=False,
    )
    blockers = _legacy_cleanup_blockers(
        project_root=root,
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        verification=verification,
    )
    return {
        "schemaVersion": 1,
        "mode": "legacy_workspace_cleanup_preview",
        "generatedAt": _now_iso(),
        "hardDelete": True,
        "confirmationPhrase": LEGACY_WORKSPACE_CLEANUP_CONFIRMATION,
        "canExecute": not blockers,
        "blockedReasons": blockers,
        "sourceWorkspace": str(source_workspace),
        "targetWorkspace": str(target_workspace),
        "verification": verification,
        "path": {
            "path": _display_path(source_workspace, project_root=root),
            "absolutePath": str(source_workspace),
            "kind": "directory",
            "action": "delete",
            "exists": source_workspace.exists(),
            **_path_summary(source_workspace),
        },
    }


def execute_legacy_workspace_cleanup(
    *,
    confirmation_phrase: str,
    project_root: Path | None = None,
    data_home: str | Path | None = None,
    config_path: str | Path | None = None,
    excludes: set[str] | None = None,
) -> dict[str, Any]:
    preview = preview_legacy_workspace_cleanup(
        project_root=project_root,
        data_home=data_home,
        config_path=config_path,
        excludes=excludes,
    )
    if str(confirmation_phrase or "").strip() != LEGACY_WORKSPACE_CLEANUP_CONFIRMATION:
        raise WorkspaceDataMigrationError("Legacy workspace cleanup confirmation phrase does not match.")
    if preview["blockedReasons"]:
        raise WorkspaceDataMigrationError(f"Legacy workspace cleanup is blocked: {', '.join(preview['blockedReasons'])}")

    source_workspace = Path(preview["sourceWorkspace"]).resolve()
    stats = _path_summary(source_workspace)
    try:
        shutil.rmtree(source_workspace)
    except Exception as exc:
        _record_workspace_event(
            "legacy_cleanup",
            "workspace_data_migration.legacy_cleanup_failed",
            level="error",
            outcome="failed",
            fields={"sourceWorkspace": str(source_workspace), "error": f"{type(exc).__name__}: {exc}"},
        )
        raise WorkspaceDataMigrationError(f"Failed to delete legacy workspace: {exc}") from exc

    result = {
        **preview,
        "mode": "legacy_workspace_cleanup_execute",
        "executed": True,
        "deleted": {
            "path": preview["path"]["path"],
            "absolutePath": str(source_workspace),
            "fileCount": stats["fileCount"],
            "byteCount": stats["sizeBytes"],
            "status": "deleted",
        },
    }
    _record_workspace_event(
        "legacy_cleanup",
        "workspace_data_migration.legacy_workspace_deleted",
        outcome="succeeded",
        fields={
            "sourceWorkspace": str(source_workspace),
            "fileCount": stats["fileCount"],
            "byteCount": stats["sizeBytes"],
        },
    )
    return result


def build_report(*, action: str, source_workspace: Path, target_workspace: Path, excludes: set[str]) -> dict[str, Any]:
    source_workspace = Path(source_workspace).expanduser().resolve()
    target_workspace = Path(target_workspace).expanduser().resolve()
    exclusion_set = _normalize_excludes(excludes)
    entries = _top_level_entries(source_workspace, excludes=exclusion_set)
    items = []
    for source in entries:
        relative = source.relative_to(source_workspace)
        target = target_workspace / relative
        items.append(
            {
                "relativePath": relative.as_posix(),
                "kind": "directory" if source.is_dir() else "file",
                "sourcePath": str(source),
                "targetPath": str(target),
                "sourceExists": source.exists(),
                "targetExists": target.exists(),
                "source": _path_summary(source),
                "target": _path_summary(target),
            }
        )
    totals = {
        "itemCount": len(items),
        "sourceSizeBytes": sum(int((item.get("source") or {}).get("sizeBytes") or 0) for item in items),
        "targetSizeBytes": sum(int((item.get("target") or {}).get("sizeBytes") or 0) for item in items),
        "sourceFileCount": sum(int((item.get("source") or {}).get("fileCount") or 0) for item in items),
        "targetFileCount": sum(int((item.get("target") or {}).get("fileCount") or 0) for item in items),
        "targetExistingCount": sum(1 for item in items if item.get("targetExists")),
    }
    return {
        "schemaVersion": 2,
        "mode": "external_workspace_migration",
        "action": action,
        "generatedAt": _now_iso(),
        "sourceWorkspace": str(source_workspace),
        "targetWorkspace": str(target_workspace),
        "sourceExists": source_workspace.exists(),
        "targetExists": target_workspace.exists(),
        "samePath": _same_path(source_workspace, target_workspace),
        "excludes": sorted(exclusion_set),
        "items": items,
        "totals": totals,
        "applied": False,
        "verified": {},
        "deletesProjectWorkspace": False,
        "manifestPath": str(target_workspace / WORKSPACE_MANIFEST_NAME),
    }


def apply_migration(report: dict[str, Any], *, data_home: str | Path | None = None, config_path: str | Path | None = None) -> None:
    source_workspace = Path(str(report.get("sourceWorkspace") or "")).resolve()
    target_workspace = Path(str(report.get("targetWorkspace") or "")).resolve()
    if _same_path(source_workspace, target_workspace):
        raise WorkspaceDataMigrationError("Source and target workspace are the same path; migration is not needed.")
    backup_root = resolve_data_backup_dir(data_home, config_path=config_path) / f"workspace-migration-{_timestamp()}"
    target_workspace.mkdir(parents=True, exist_ok=True)
    for item in list(report.get("items") or []):
        source = Path(str(item.get("sourcePath") or "")).resolve()
        target = Path(str(item.get("targetPath") or "")).resolve()
        if not source.exists():
            continue
        if not _is_relative_to(source, source_workspace):
            raise WorkspaceDataMigrationError(f"Refusing to copy source outside workspace: {source}")
        if not _is_relative_to(target, target_workspace):
            raise WorkspaceDataMigrationError(f"Refusing to write target outside workspace: {target}")
        if target.exists():
            backup_target = backup_root / "workspace" / Path(str(item.get("relativePath") or ""))
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, backup_target, dirs_exist_ok=True)
            else:
                shutil.copy2(target, backup_target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    report["backupRoot"] = str(backup_root)


def verify_migration(report: dict[str, Any]) -> dict[str, Any]:
    mismatches = []
    for item in list(report.get("items") or []):
        source = Path(str(item.get("sourcePath") or ""))
        target = Path(str(item.get("targetPath") or ""))
        source_summary = _path_summary(source)
        target_summary = _path_summary(target)
        if _verification_projection(source_summary) != _verification_projection(target_summary):
            mismatches.append(
                {
                    "relativePath": str(item.get("relativePath") or ""),
                    "source": source_summary,
                    "target": target_summary,
                }
            )
    return {
        "ok": not mismatches,
        "mismatchCount": len(mismatches),
        "mismatches": mismatches[:50],
        "checkedAt": _now_iso(),
        "verificationMode": "sha256_tree_manifest",
    }


def write_workspace_manifest(target_workspace: Path, *, excludes: set[str] | None = None) -> dict[str, Any]:
    target = Path(target_workspace).expanduser().resolve()
    manifest = _workspace_manifest(target, excludes=_normalize_excludes(excludes))
    manifest_path = target / WORKSPACE_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _workspace_manifest(workspace: Path, *, excludes: set[str]) -> dict[str, Any]:
    entries = _top_level_entries(workspace, excludes=excludes)
    items = []
    for entry in entries:
        items.append(
            {
                "relativePath": entry.relative_to(workspace).as_posix(),
                "kind": "directory" if entry.is_dir() else "file",
                **_path_summary(entry),
            }
        )
    return {
        "schemaVersion": 1,
        "generatedAt": _now_iso(),
        "workspaceRoot": str(workspace),
        "items": items,
        "totals": {
            "itemCount": len(items),
            "fileCount": sum(int(item.get("fileCount") or 0) for item in items),
            "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in items),
        },
        "treeHash": _combined_tree_hash(items),
    }


def _path_summary(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"exists": False, "kind": "", "fileCount": 0, "sizeBytes": 0, "treeHash": ""}
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        digest = _file_digest(path)
        return {"exists": True, "kind": "file", "fileCount": 1, "sizeBytes": int(size), "treeHash": digest}
    files = []
    size_bytes = 0
    for child in _iter_files(path):
        try:
            size = child.stat().st_size
        except OSError:
            size = 0
        size_bytes += size
        files.append({"relativePath": child.relative_to(path).as_posix(), "sizeBytes": int(size), "sha256": _file_digest(child)})
    return {
        "exists": True,
        "kind": "directory",
        "fileCount": len(files),
        "sizeBytes": int(size_bytes),
        "treeHash": _combined_tree_hash(files),
    }


def _top_level_entries(source_workspace: Path, *, excludes: set[str]) -> list[Path]:
    if not source_workspace.exists():
        return []
    return [
        item
        for item in sorted(source_workspace.iterdir(), key=lambda path: path.name.casefold())
        if item.name not in excludes
    ]


def _iter_files(root: Path) -> Iterable[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.as_posix().casefold())


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return f"sha256:{digest.hexdigest()}"


def _combined_tree_hash(items: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(items, key=lambda value: str(value.get("relativePath") or "")):
        digest.update(str(item.get("relativePath") or "").encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(item.get("sizeBytes") or 0).encode("ascii", errors="replace"))
        digest.update(b"\0")
        digest.update(str(item.get("sha256") or item.get("treeHash") or "").encode("utf-8", errors="replace"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _verification_projection(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "exists": bool(summary.get("exists")),
        "kind": str(summary.get("kind") or ""),
        "fileCount": int(summary.get("fileCount") or 0),
        "sizeBytes": int(summary.get("sizeBytes") or 0),
        "treeHash": str(summary.get("treeHash") or ""),
    }


def _legacy_cleanup_blockers(
    *,
    project_root: Path,
    source_workspace: Path,
    target_workspace: Path,
    verification: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not source_workspace.exists():
        blockers.append("legacy_workspace_missing")
    if _same_path(source_workspace, target_workspace):
        blockers.append("source_and_target_same_path")
    if source_workspace.resolve() != (project_root.resolve() / "workspace").resolve():
        blockers.append("legacy_workspace_path_not_project_workspace")
    if not target_workspace.exists():
        blockers.append("target_workspace_missing")
    if not bool(verification.get("ok")):
        blockers.append("migration_not_verified")
    if _contains_symlink(source_workspace):
        blockers.append("legacy_workspace_contains_symlink")
    return blockers


def _contains_symlink(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_symlink():
        return True
    if path.is_dir():
        try:
            return any(child.is_symlink() for child in path.rglob("*"))
        except OSError:
            return True
    return False


def _normalize_excludes(excludes: set[str] | None) -> set[str]:
    result = set(DEFAULT_TOP_LEVEL_EXCLUDES)
    result.update(str(item or "").strip() for item in (excludes or set()) if str(item or "").strip())
    return result


def _source_workspace(project_root: Path) -> Path:
    return project_root.resolve() / "workspace"


def _project_root(project_root: Path | None = None) -> Path:
    return Path(project_root or PROJECT_ROOT).expanduser().resolve()


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return Path(left).absolute() == Path(right).absolute()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _display_path(path: Path, *, project_root: Path) -> str:
    resolved = path.resolve()
    root = project_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        pass
    try:
        workspace_root = resolve_workspace_home().resolve()
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        return str(path)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_report(path_value: str | Path | None, report: dict[str, Any]) -> None:
    if not str(path_value or "").strip():
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record_workspace_event(
    phase: str,
    event_code: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "storage",
            phase,
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        return


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
