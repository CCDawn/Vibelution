"""Transactional Git integration for supervised evolution candidates."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from core.infrastructure import git_process


class CandidateIntegrationError(RuntimeError):
    """Raised when a candidate cannot be integrated without losing evidence."""


def integrate_candidate(
    *,
    project_root: Path,
    candidate_root: Path,
    changed_files: list[dict[str, Any]],
    expected_head: str,
    expected_variant_id: str,
    run_id: str,
    manifest_root: Path,
) -> dict[str, Any]:
    """Apply the frozen candidate as one exact, auditable local Git commit."""

    root = Path(project_root).resolve()
    candidate = Path(candidate_root).resolve()
    normalized_paths = _normalized_changed_paths(changed_files)
    if not normalized_paths:
        raise CandidateIntegrationError("候选差异为空，禁止创建合入提交。")
    if not candidate.is_dir():
        raise CandidateIntegrationError("候选工作树不可用，禁止创建合入提交。")

    branch = _git_text(root, "branch", "--show-current")
    if branch != "main":
        raise CandidateIntegrationError(f"受控合入只允许写入 main；当前分支为 {branch or 'detached'}。")
    dirty = _status_entries(root)
    if dirty:
        raise CandidateIntegrationError(
            f"主工作区必须完全干净后才能自动合入；当前存在 {len(dirty)} 项改动。"
        )
    current_head = _git_text(root, "rev-parse", "HEAD")
    frozen_head = str(expected_head or "").strip()
    if not frozen_head or current_head != frozen_head:
        raise CandidateIntegrationError(
            f"主工作区 HEAD 已偏离冻结检查点；expected={frozen_head or 'missing'}，"
            f"actual={current_head or 'missing'}。"
        )
    variant_id = str(expected_variant_id or "").strip()
    if not variant_id:
        raise CandidateIntegrationError("候选版本未绑定，禁止创建合入提交。")

    manifest = _build_manifest(
        root=root,
        candidate=candidate,
        paths=normalized_paths,
        changed_files=changed_files,
        run_id=run_id,
        base_commit=current_head,
        variant_id=variant_id,
    )
    manifest_path = _write_manifest(Path(manifest_root), manifest)
    applied = False
    try:
        _apply_candidate(root=root, candidate=candidate, entries=manifest["entries"])
        applied = True
        _verify_candidate_content(root=root, candidate=candidate, entries=manifest["entries"])
        _run_git_checked(root, "add", "--all", "--", *normalized_paths)
        staged = _nul_paths(_git_bytes(root, "diff", "--cached", "--name-only", "-z"))
        if staged != sorted(normalized_paths):
            raise CandidateIntegrationError(
                "暂存区与冻结候选文件集合不一致，已中止自动合入。"
            )
        commit_result = git_process.run_git(
            [
                "commit",
                "-m",
                f"evolve(supervised): apply {str(run_id or '').strip()}",
                "-m",
                (
                    f"Supervised-Run: {str(run_id or '').strip()}\n"
                    f"Candidate-Variant: {variant_id}\n"
                    f"Base-Commit: {current_head}"
                ),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if commit_result.returncode != 0:
            detail = str(commit_result.stderr or commit_result.stdout or "").strip()
            raise CandidateIntegrationError(f"Git 提交失败：{detail or 'unknown error'}")
        commit_sha = _git_text(root, "rev-parse", "HEAD")
        if not commit_sha or commit_sha == current_head:
            raise CandidateIntegrationError("Git 提交未推进 HEAD，已中止自动合入。")
        remaining = _status_entries(root)
        if remaining:
            raise CandidateIntegrationError(
                f"候选提交后主工作区仍有 {len(remaining)} 项改动，不能声明合入完成。"
            )
    except Exception as exc:
        if applied:
            recovery_error = _restore_before_commit(root=root, manifest=manifest)
            if recovery_error:
                raise CandidateIntegrationError(
                    f"{exc}；自动恢复失败：{recovery_error}"
                ) from exc
        if isinstance(exc, CandidateIntegrationError):
            raise
        raise CandidateIntegrationError(str(exc)) from exc

    return {
        "status": "committed",
        "mechanism": "controlled_candidate_commit",
        "baseCommit": current_head,
        "commitSha": commit_sha,
        "candidateVariantId": variant_id,
        "changedFiles": normalized_paths,
        "rollbackManifestPath": str(manifest_path),
        "committedAt": _now_iso(),
    }


def revert_candidate_commit(
    *,
    project_root: Path,
    integration_commit: str,
    run_id: str,
) -> dict[str, Any]:
    """Create an auditable revert commit for a previously integrated candidate."""

    root = Path(project_root).resolve()
    commit_sha = str(integration_commit or "").strip()
    if not commit_sha:
        raise CandidateIntegrationError("缺少候选合入提交，不能执行回退。")
    if _status_entries(root):
        raise CandidateIntegrationError("主工作区必须完全干净后才能回退候选提交。")
    current_head = _git_text(root, "rev-parse", "HEAD")
    if current_head != commit_sha:
        raise CandidateIntegrationError(
            "自动回退仅允许在候选合入提交仍为当前 HEAD 时执行，避免覆盖后续提交。"
        )
    result = git_process.run_git(
        ["revert", "--no-edit", commit_sha],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or "").strip()
        raise CandidateIntegrationError(f"Git revert 失败：{detail or 'unknown error'}")
    revert_sha = _git_text(root, "rev-parse", "HEAD")
    if not revert_sha or revert_sha == commit_sha or _status_entries(root):
        raise CandidateIntegrationError("Git revert 未形成干净、可审计的新提交。")
    return {
        "status": "reverted",
        "runId": str(run_id or "").strip(),
        "revertedCommit": commit_sha,
        "revertCommit": revert_sha,
        "revertedAt": _now_iso(),
    }


def _normalized_changed_paths(changed_files: list[dict[str, Any]]) -> list[str]:
    paths: set[str] = set()
    for item in changed_files:
        raw = str(item.get("path") or "").strip().replace("\\", "/")
        path = PurePosixPath(raw)
        if (
            not raw
            or path.is_absolute()
            or raw.startswith("/")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise CandidateIntegrationError(f"候选路径不安全：{raw or '<empty>'}")
        paths.add(path.as_posix())
    return sorted(paths)


def _build_manifest(
    *,
    root: Path,
    candidate: Path,
    paths: list[str],
    changed_files: list[dict[str, Any]],
    run_id: str,
    base_commit: str,
    variant_id: str,
) -> dict[str, Any]:
    change_types = {
        str(item.get("path") or "").strip().replace("\\", "/"): str(
            item.get("changeType") or ""
        ).strip()
        for item in changed_files
    }
    entries: list[dict[str, Any]] = []
    for relative in paths:
        target = _safe_path(root, relative)
        source = _safe_path(candidate, relative)
        if target.exists() and not target.is_file():
            raise CandidateIntegrationError(f"目标不是普通文件：{relative}")
        if source.exists() and not source.is_file():
            raise CandidateIntegrationError(f"候选不是普通文件：{relative}")
        before = target.read_bytes() if target.exists() else b""
        after = source.read_bytes() if source.exists() else b""
        declared_type = change_types.get(relative, "")
        if declared_type != "deleted" and not source.exists():
            raise CandidateIntegrationError(f"候选文件缺失：{relative}")
        entries.append(
            {
                "path": relative,
                "changeType": "deleted" if not source.exists() else declared_type,
                "existed": target.exists(),
                "contentBase64": base64.b64encode(before).decode("ascii"),
                "beforeSha256": _sha256(before) if target.exists() else "",
                "afterSha256": _sha256(after) if source.exists() else "",
            }
        )
    return {
        "schemaVersion": 2,
        "runId": str(run_id or "").strip(),
        "createdAt": _now_iso(),
        "baseCommit": base_commit,
        "candidateVariantId": variant_id,
        "entries": entries,
    }


def _write_manifest(manifest_root: Path, manifest: dict[str, Any]) -> Path:
    root = Path(manifest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = str(manifest.get("runId") or "unknown").strip() or "unknown"
    path = root / f"{run_id}-{str(manifest.get('candidateVariantId') or '')[:12]}.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _apply_candidate(*, root: Path, candidate: Path, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        relative = str(entry["path"])
        target = _safe_path(root, relative)
        source = _safe_path(candidate, relative)
        if str(entry.get("changeType") or "") == "deleted" or not source.exists():
            if target.exists():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _verify_candidate_content(
    *,
    root: Path,
    candidate: Path,
    entries: list[dict[str, Any]],
) -> None:
    for entry in entries:
        relative = str(entry["path"])
        target = _safe_path(root, relative)
        source = _safe_path(candidate, relative)
        if str(entry.get("changeType") or "") == "deleted" or not source.exists():
            if target.exists():
                raise CandidateIntegrationError(f"删除候选仍存在于目标：{relative}")
            continue
        if not target.is_file() or _sha256(target.read_bytes()) != str(entry.get("afterSha256") or ""):
            raise CandidateIntegrationError(f"候选文件内容校验失败：{relative}")


def _restore_before_commit(*, root: Path, manifest: dict[str, Any]) -> str:
    paths = [str(entry["path"]) for entry in list(manifest.get("entries") or [])]
    if paths:
        git_process.run_git(
            ["restore", "--staged", "--", *paths],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    for entry in list(manifest.get("entries") or []):
        target = _safe_path(root, str(entry["path"]))
        if bool(entry.get("existed")):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(str(entry.get("contentBase64") or "")))
        elif target.exists():
            target.unlink()
    remaining = _status_entries(root)
    return "" if not remaining else f"恢复后仍有 {len(remaining)} 项改动"


def _safe_path(root: Path, relative: str) -> Path:
    target = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise CandidateIntegrationError(f"候选路径越界：{relative}") from exc
    return target


def _status_entries(root: Path) -> list[str]:
    return _nul_paths(
        _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    )


def _git_text(root: Path, *args: str) -> str:
    result = _run_git_checked(
        root,
        *args,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return str(result.stdout or "").strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = _run_git_checked(root, *args, text=False)
    value = result.stdout or b""
    return value if isinstance(value, bytes) else str(value).encode("utf-8")


def _run_git_checked(root: Path, *args: str, **kwargs: Any):
    result = git_process.run_git(
        list(args),
        cwd=root,
        capture_output=True,
        check=False,
        **kwargs,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
        stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout or "")
        raise CandidateIntegrationError((stderr or stdout or "Git command failed").strip())
    return result


def _nul_paths(value: bytes) -> list[str]:
    return sorted(
        item.decode("utf-8", errors="replace")
        for item in value.split(b"\0")
        if item
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
