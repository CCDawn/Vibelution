"""Launcher-owned developer mode and guarded cleanup plans."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from config.public_config import CONFIG_PATH, load_public_config, public_config_hash, save_public_config
from core.runtime_manager.constants import PROJECT_ROOT
from core.runtime_manager.scene_logging import append_runtime_manager_file_event


DeveloperCleanupAction = Literal["quick_clean", "db_compact", "worktree_cleanup"]

DEVELOPER_MODE_SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 1
PLAN_TTL_MINUTES = 30
WORKTREE_SNAPSHOT_KEEP_LATEST = 50
DEVELOPER_MODE_PLAN_DIR = PROJECT_ROOT / ".runtime" / "launcher" / "developer-mode-plans"
QUICK_CLEAN_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".vitest"}
QUICK_CLEAN_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".runtime",
    ".docs",
    "workspace",
    "logs",
    "log_info",
}
PROTECTED_PROJECT_NAMES = {
    "AGENTS.md",
    "DEVELOPMENT_STANDARD.md",
    "PROJECT_MEMORY.html",
    "config.toml",
    "config.example.toml",
}


class DeveloperModeDisabled(PermissionError):
    """Raised when a developer-mode-only operation is requested while disabled."""


class DeveloperCleanupPlanError(ValueError):
    """Raised when a cleanup plan cannot be applied safely."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def get_developer_mode_setting(*, config_path: Path | None = None) -> dict[str, Any]:
    """Return the Launcher-owned developer mode state. Missing config means off."""

    public_config = _load_public_config(config_path)
    launcher = _read_section(public_config, "launcher")
    raw_setting = launcher.get("developer_mode") if isinstance(launcher.get("developer_mode"), dict) else {}
    enabled = bool(raw_setting.get("enabled", False)) if isinstance(raw_setting, dict) else False
    return {
        "schemaVersion": DEVELOPER_MODE_SCHEMA_VERSION,
        "enabled": enabled,
        "defaulted": not bool(raw_setting),
        "updatedAt": str(raw_setting.get("updated_at") or "") if isinstance(raw_setting, dict) else "",
        "updatedBy": str(raw_setting.get("updated_by") or "") if isinstance(raw_setting, dict) else "",
        "controller": "launcher",
        "configPath": str(config_path or CONFIG_PATH),
        "configHash": public_config_hash(public_config),
        "policy": {
            "settingsPageMutable": False,
            "requiresLauncher": True,
            "requiresPreview": True,
            "requiresPlanHash": True,
            "requiresConfirm": True,
            "defaultWhenMissing": False,
        },
    }


def update_developer_mode_setting(
    enabled: object,
    *,
    base_hash: str = "",
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Persist developer mode under launcher.developer_mode in external config."""

    public_config = load_public_config(config_path or CONFIG_PATH)
    current_hash = public_config_hash(public_config)
    expected_hash = str(base_hash or "").strip()
    if expected_hash and expected_hash != current_hash:
        _record_event(
            "launcher.developer_mode.conflict",
            phase="settings",
            outcome="conflict",
            level="warning",
            message="Launcher developer mode update rejected because the config snapshot is stale.",
            fields={"baseHash": expected_hash, "currentHash": current_hash, "configPath": str(config_path or CONFIG_PATH)},
        )
        raise DeveloperCleanupPlanError(
            "developer_mode_config_conflict",
            "开发者模式保存前配置已被其他页面或进程改动，请刷新 Launcher 后重试。",
        )
    normalized = _parse_bool(enabled, label="enabled")
    launcher = _ensure_section(public_config, "launcher")
    previous = get_developer_mode_setting(config_path=config_path)
    launcher["developer_mode"] = {
        "enabled": normalized,
        "updated_at": _utcnow(),
        "updated_by": "launcher",
    }
    save_public_config(public_config, config_path or CONFIG_PATH)
    setting = get_developer_mode_setting(config_path=config_path)
    _record_event(
        "launcher.developer_mode.updated",
        phase="settings",
        outcome="succeeded",
        message="Launcher developer mode setting updated.",
        fields={
            "previousEnabled": previous["enabled"],
            "enabled": setting["enabled"],
            "configPath": setting["configPath"],
            "previousHash": current_hash,
            "configHash": setting["configHash"],
        },
    )
    return {
        "ok": True,
        "setting": setting,
        "message": "开发者模式已由 Launcher 保存。",
    }


def get_noise_overview(*, config_path: Path | None = None, project_root: Path | None = None) -> dict[str, Any]:
    """Return a read-only cleanup/noise overview. This is available even when mode is off."""

    root = _project_root(project_root)
    quick_targets = _quick_clean_targets(root)
    worktree_targets, worktree_skipped = _worktree_cleanup_candidates(root)
    db_path = root / "workspace" / "agent_brain.db"
    daemon_log_path = root / ".runtime" / "runtime-manager" / "daemon.out.log"
    items = [
        _overview_item(
            "git_memory_db",
            "Git memory SQLite",
            db_path,
            action="db_compact",
            protected=False,
            reason="仅通过 GitMemoryService prune + VACUUM 压缩旧 wt-* 快照。",
        ),
        _overview_item(
            "runtime_manager_log",
            "Runtime manager log",
            daemon_log_path,
            action="manual_review",
            protected=True,
            reason="运行中日志不在首版自动清理白名单内。",
        ),
        {
            "id": "quick_clean_candidates",
            "label": "Quick clean whitelist",
            "path": str(root),
            "exists": bool(quick_targets),
            "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in quick_targets),
            "targetCount": len(quick_targets),
            "action": "quick_clean",
            "protected": False,
            "reason": "只包含缓存、构建产物和 __pycache__ 等白名单目标。",
        },
        {
            "id": "worktree_cleanup_candidates",
            "label": "Merged clean worktrees",
            "path": str(_worktrees_root(root)),
            "exists": bool(worktree_targets),
            "sizeBytes": sum(int(item.get("sizeBytes") or 0) for item in worktree_targets),
            "targetCount": len(worktree_targets),
            "skippedCount": len(worktree_skipped),
            "action": "worktree_cleanup",
            "protected": False,
            "reason": "只列出位于 Vibelution-worktrees 下、clean 且 branch tip 已并入 main 的 worktree。",
        },
    ]
    return {
        "schemaVersion": DEVELOPER_MODE_SCHEMA_VERSION,
        "developerMode": get_developer_mode_setting(config_path=config_path),
        "projectRoot": str(root),
        "items": items,
        "updatedAt": _utcnow(),
    }


def preview_cleanup_plan(
    action: str,
    *,
    config_path: Path | None = None,
    project_root: Path | None = None,
    plan_dir: Path | None = None,
) -> dict[str, Any]:
    """Build and persist a dry-run cleanup plan."""

    normalized = _parse_action(action)
    mode = get_developer_mode_setting(config_path=config_path)
    if not mode["enabled"]:
        raise DeveloperModeDisabled("开发者模式未开启，无法生成清理计划。")
    root = _project_root(project_root)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=PLAN_TTL_MINUTES)
    targets, skipped = _targets_for_action(normalized, root)
    plan = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "planId": f"devplan-{uuid.uuid4().hex[:12]}",
        "planHash": "",
        "action": normalized,
        "createdAt": _format_dt(now),
        "expiresAt": _format_dt(expires_at),
        "projectRoot": str(root),
        "targetCount": len(targets),
        "estimatedBytes": sum(int(item.get("sizeBytes") or 0) for item in targets),
        "targets": targets,
        "skipped": skipped,
        "requiresConfirm": True,
        "applyContract": {
            "requiresDeveloperMode": True,
            "requiresPlanId": True,
            "requiresPlanHash": True,
            "requiresConfirm": True,
        },
    }
    plan["planHash"] = _plan_hash(plan)
    _store_plan(plan, plan_dir=plan_dir)
    _record_event(
        "launcher.developer_mode.cleanup.previewed",
        phase="maintenance",
        outcome="previewed",
        message="Launcher developer cleanup plan previewed.",
        fields={
            "action": normalized,
            "planId": plan["planId"],
            "planHash": plan["planHash"],
            "targetCount": plan["targetCount"],
            "estimatedBytes": plan["estimatedBytes"],
        },
    )
    return {
        "ok": True,
        "mode": "preview",
        "developerMode": mode,
        "plan": plan,
        "message": "清理计划已生成，执行前仍需要 planId、planHash 和确认。",
    }


def apply_cleanup_plan(
    action: str,
    *,
    plan_id: str,
    plan_hash: str,
    confirm: bool,
    config_path: Path | None = None,
    project_root: Path | None = None,
    plan_dir: Path | None = None,
) -> dict[str, Any]:
    """Apply a previously previewed cleanup plan after all guards pass."""

    normalized = _parse_action(action)
    if not confirm:
        raise DeveloperCleanupPlanError("confirm_required", "执行清理前必须显式确认。")
    mode = get_developer_mode_setting(config_path=config_path)
    if not mode["enabled"]:
        raise DeveloperModeDisabled("开发者模式未开启，无法执行清理计划。")
    plan = _load_plan(plan_id, plan_dir=plan_dir)
    if str(plan.get("action") or "") != normalized:
        raise DeveloperCleanupPlanError("action_mismatch", "清理计划动作与当前请求不一致。")
    if str(plan.get("planHash") or "") != str(plan_hash or "").strip():
        raise DeveloperCleanupPlanError("plan_hash_mismatch", "清理计划 hash 不匹配，请重新预览。")
    if _plan_hash(plan) != str(plan_hash or "").strip():
        raise DeveloperCleanupPlanError("plan_hash_mismatch", "清理计划内容已变化，请重新预览。")
    if _is_expired(str(plan.get("expiresAt") or "")):
        raise DeveloperCleanupPlanError("plan_expired", "清理计划已过期，请重新预览。")
    root = _project_root(project_root)
    if Path(str(plan.get("projectRoot") or "")).resolve() != root:
        raise DeveloperCleanupPlanError("project_root_mismatch", "清理计划不属于当前项目工作区。")
    _validate_targets_still_safe(plan, root)
    applied = _apply_targets(plan, root)
    _record_event(
        "launcher.developer_mode.cleanup.applied",
        phase="maintenance",
        outcome="succeeded",
        message="Launcher developer cleanup plan applied.",
        fields={
            "action": normalized,
            "planId": plan["planId"],
            "targetCount": len(applied),
            "reclaimedBytes": sum(int(item.get("sizeBytes") or 0) for item in applied),
        },
    )
    return {
        "ok": True,
        "mode": "apply",
        "developerMode": mode,
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "action": normalized,
        "applied": applied,
        "reclaimedBytes": sum(int(item.get("sizeBytes") or 0) for item in applied),
        "message": "清理计划已执行。",
    }


def _load_public_config(config_path: Path | None) -> dict[str, Any]:
    try:
        public_config = load_public_config(config_path or CONFIG_PATH)
    except Exception:
        return {}
    return public_config if isinstance(public_config, dict) else {}


def _read_section(payload: dict[str, Any], section: str) -> dict[str, Any]:
    value = payload.get(section) if isinstance(payload, dict) else {}
    return value if isinstance(value, dict) else {}


def _ensure_section(payload: dict[str, Any], section: str) -> dict[str, Any]:
    value = payload.get(section)
    if isinstance(value, dict):
        return value
    value = {}
    payload[section] = value
    return value


def _parse_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{label} must be a boolean")


def _parse_action(action: str) -> DeveloperCleanupAction:
    normalized = str(action or "").strip().lower()
    if normalized in {"quick_clean", "db_compact", "worktree_cleanup"}:
        return normalized  # type: ignore[return-value]
    raise ValueError("Unsupported developer cleanup action")


def _project_root(project_root: Path | None) -> Path:
    return Path(project_root or PROJECT_ROOT).resolve()


def _worktrees_root(root: Path) -> Path:
    return root.parent / "Vibelution-worktrees"


def _overview_item(
    item_id: str,
    label: str,
    path: Path,
    *,
    action: str,
    protected: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "path": str(path),
        "exists": path.exists(),
        "sizeBytes": _path_size(path) if path.exists() else 0,
        "targetCount": 1 if path.exists() else 0,
        "action": action,
        "protected": protected,
        "reason": reason,
    }


def _targets_for_action(action: DeveloperCleanupAction, root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if action == "quick_clean":
        return _quick_clean_targets(root), []
    if action == "db_compact":
        db_path = root / "workspace" / "agent_brain.db"
        if not db_path.is_file():
            return [], [{"path": str(db_path), "reason": "agent_brain.db 不存在"}]
        return [_target_payload(db_path, root=root, operation="prune_worktree_snapshots_vacuum")], []
    return _worktree_cleanup_candidates(root)


def _quick_clean_targets(root: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for current_root, dir_names, file_names in os.walk(root):
        current = Path(current_root)
        rel_parts = set(current.relative_to(root).parts) if current != root else set()
        if rel_parts & QUICK_CLEAN_EXCLUDED_DIRS:
            dir_names[:] = []
            continue
        dir_names[:] = [name for name in dir_names if name not in QUICK_CLEAN_EXCLUDED_DIRS]
        for dirname in list(dir_names):
            candidate = current / dirname
            if dirname in QUICK_CLEAN_DIR_NAMES and _is_safe_quick_clean_target(candidate, root):
                targets.append(_target_payload(candidate, root=root, operation="delete"))
                dir_names.remove(dirname)
        if current == root / "web":
            for dirname in ("dist", ".vite"):
                candidate = current / dirname
                if candidate.exists() and _is_safe_quick_clean_target(candidate, root):
                    targets.append(_target_payload(candidate, root=root, operation="delete"))
        if current.name == "web":
            for filename in file_names:
                if filename.endswith(".tsbuildinfo") or filename.startswith("vite.config.") and ".timestamp-" in filename:
                    candidate = current / filename
                    if _is_safe_quick_clean_target(candidate, root):
                        targets.append(_target_payload(candidate, root=root, operation="delete"))
    return _dedupe_targets(targets)


def _is_safe_quick_clean_target(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    if not _is_relative_to(resolved, root):
        return False
    if resolved.name in PROTECTED_PROJECT_NAMES:
        return False
    rel_parts = set(resolved.relative_to(root).parts)
    if ".docs" in rel_parts or "workspace" in rel_parts or "logs" in rel_parts or "log_info" in rel_parts:
        return False
    return (
        resolved.name in QUICK_CLEAN_DIR_NAMES
        or resolved == root / "web" / "dist"
        or resolved == root / "web" / ".vite"
        or resolved.name.endswith(".tsbuildinfo")
        or (resolved.name.startswith("vite.config.") and ".timestamp-" in resolved.name)
    )


def _worktree_cleanup_candidates(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    worktrees_root = _worktrees_root(root).resolve()
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in _git_worktrees(root):
        path = Path(item.get("path") or "").resolve()
        if path == root or not _is_relative_to(path, worktrees_root):
            continue
        branch = str(item.get("branch") or "")
        head = str(item.get("head") or "")
        reason = _worktree_skip_reason(path, branch, head, root)
        if reason:
            skipped.append({"path": str(path), "branch": branch, "head": head, "reason": reason})
            continue
        targets.append(_target_payload(path, root=worktrees_root, operation="git_worktree_remove", extra={"branch": branch, "head": head}))
    return targets, skipped


def _git_worktrees(root: Path) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                items.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                items.append(current)
            current = {"path": value.strip()}
        elif key in {"HEAD", "branch"}:
            current[key.lower()] = value.strip()
    if current:
        items.append(current)
    return items


def _worktree_skip_reason(path: Path, branch_ref: str, head: str, root: Path) -> str:
    if not path.exists():
        return "worktree 路径不存在"
    if not (path / ".git").exists():
        return "不是 Git worktree"
    if _git_status_dirty(path):
        return "worktree 存在未提交改动"
    if not head:
        return "缺少 HEAD，无法证明已合并"
    if not _git_head_merged_to_main(root, head):
        return "branch tip 尚未并入 main"
    if branch_ref.endswith("/main"):
        return "主分支 worktree 受保护"
    return ""


def _git_status_dirty(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return True
    return result.returncode != 0 or bool(result.stdout.strip())


def _git_head_merged_to_main(root: Path, head: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", head, "main"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return False
    return result.returncode == 0


def _target_payload(path: Path, *, root: Path, operation: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    payload = {
        "path": str(resolved),
        "relativePath": _relative_display(resolved, root),
        "kind": "directory" if resolved.is_dir() else "file" if resolved.is_file() else "missing",
        "operation": operation,
        "sizeBytes": _path_size(resolved) if resolved.exists() else 0,
        "mtimeNs": resolved.stat().st_mtime_ns if resolved.exists() else 0,
    }
    if extra:
        payload.update(extra)
    return payload


def _dedupe_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        path = str(target.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        deduped.append(target)
    return deduped


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _store_plan(plan: dict[str, Any], *, plan_dir: Path | None) -> None:
    directory = Path(plan_dir or DEVELOPER_MODE_PLAN_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{plan['planId']}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_plan(plan_id: str, *, plan_dir: Path | None) -> dict[str, Any]:
    normalized = str(plan_id or "").strip()
    if not normalized or not normalized.startswith("devplan-") or not normalized.replace("devplan-", "").isalnum():
        raise DeveloperCleanupPlanError("invalid_plan_id", "清理计划 ID 无效。")
    path = Path(plan_dir or DEVELOPER_MODE_PLAN_DIR) / f"{normalized}.json"
    if not path.is_file():
        raise DeveloperCleanupPlanError("plan_not_found", "清理计划不存在，请重新预览。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DeveloperCleanupPlanError("plan_unreadable", "清理计划无法读取，请重新预览。") from exc
    if not isinstance(payload, dict):
        raise DeveloperCleanupPlanError("plan_unreadable", "清理计划格式无效，请重新预览。")
    return payload


def _plan_hash(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload["planHash"] = ""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_expired(expires_at: str) -> bool:
    try:
        deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) > deadline


def _validate_targets_still_safe(plan: dict[str, Any], root: Path) -> None:
    action = _parse_action(str(plan.get("action") or ""))
    targets = plan.get("targets") if isinstance(plan.get("targets"), list) else []
    for target in targets:
        if not isinstance(target, dict):
            raise DeveloperCleanupPlanError("invalid_target", "清理计划包含无效目标。")
        path = Path(str(target.get("path") or "")).resolve()
        if action in {"quick_clean", "db_compact"} and not _is_relative_to(path, root):
            raise DeveloperCleanupPlanError("target_outside_project", "清理目标不属于当前项目工作区。", detail={"path": str(path)})
        if action == "quick_clean" and not _is_safe_quick_clean_target(path, root):
            raise DeveloperCleanupPlanError("target_not_whitelisted", "清理目标不在 quick clean 白名单内。", detail={"path": str(path)})
        if action == "worktree_cleanup" and not _is_relative_to(path, _worktrees_root(root).resolve()):
            raise DeveloperCleanupPlanError("target_outside_worktrees", "worktree 清理目标不在外部 worktree 目录内。", detail={"path": str(path)})
        if action != "db_compact" and not path.exists():
            raise DeveloperCleanupPlanError("target_changed", "清理目标已变化，请重新预览。", detail={"path": str(path)})
        if path.exists():
            stat = path.stat()
            if int(target.get("mtimeNs") or 0) != stat.st_mtime_ns:
                raise DeveloperCleanupPlanError("target_changed", "清理目标已变化，请重新预览。", detail={"path": str(path)})
            if str(target.get("kind") or "") == "file" and int(target.get("sizeBytes") or 0) != stat.st_size:
                raise DeveloperCleanupPlanError("target_changed", "清理目标已变化，请重新预览。", detail={"path": str(path)})


def _apply_targets(plan: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    action = _parse_action(str(plan.get("action") or ""))
    targets = [target for target in plan.get("targets", []) if isinstance(target, dict)]
    if action == "db_compact":
        return [_apply_db_compact(root, targets[0] if targets else {})]
    applied: list[dict[str, Any]] = []
    for target in targets:
        path = Path(str(target.get("path") or "")).resolve()
        if action == "quick_clean":
            if path.is_dir():
                shutil.rmtree(path)
            elif path.is_file():
                path.unlink()
        elif action == "worktree_cleanup":
            result = subprocess.run(
                ["git", "-C", str(root), "worktree", "remove", str(path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode != 0:
                raise DeveloperCleanupPlanError(
                    "worktree_remove_failed",
                    "worktree 清理失败，已停止后续操作。",
                    detail={"path": str(path), "stderr": result.stderr[-1000:]},
                )
        applied.append(target)
    return applied


def _apply_db_compact(root: Path, target: dict[str, Any]) -> dict[str, Any]:
    db_path = root / "workspace" / "agent_brain.db"
    before_size = _path_size(db_path)
    try:
        from core.infrastructure.git_memory import prune_worktree_snapshots

        stats = prune_worktree_snapshots(keep_latest=WORKTREE_SNAPSHOT_KEEP_LATEST, vacuum=True)
    except sqlite3.OperationalError as exc:
        raise DeveloperCleanupPlanError("db_locked", "Git memory 数据库正被占用，稍后再试。") from exc
    after_size = _path_size(db_path)
    applied = dict(target)
    applied["sizeBytes"] = max(0, before_size - after_size)
    applied["dbStats"] = stats
    applied["beforeSizeBytes"] = before_size
    applied["afterSizeBytes"] = after_size
    return applied


def _relative_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _utcnow() -> str:
    return _format_dt(datetime.now(timezone.utc))


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_event(
    event_code: str,
    *,
    phase: str,
    message: str,
    fields: dict[str, Any] | None = None,
    outcome: str = "succeeded",
    level: str = "info",
) -> None:
    try:
        append_runtime_manager_file_event(
            event_code,
            {
                "component": "launcher",
                "phase": phase,
                "message": message,
                "outcome": outcome,
                "level": level,
                "fields": fields or {},
            },
            suppress_io_errors=True,
        )
    except Exception:
        return
