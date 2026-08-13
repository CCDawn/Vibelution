"""Transactional Git integration for supervised evolution candidates."""

from __future__ import annotations

import json
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
    """Promote a frozen candidate only while local main still matches its base."""

    root = Path(project_root).resolve()
    candidate = Path(candidate_root).resolve()
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

    variant_id = str(expected_variant_id or "").strip()
    if not variant_id:
        raise CandidateIntegrationError("候选版本未绑定，禁止创建合入提交。")

    frozen_head = str(expected_head or "").strip()
    if not frozen_head:
        raise CandidateIntegrationError(
            "missing_frozen_main: 候选未绑定冻结的 main 提交，禁止自动晋升。"
        )
    current_head = _git_text(root, "rev-parse", "HEAD")
    if current_head != frozen_head:
        raise CandidateIntegrationError(
            "stale_main: main 已从候选冻结基线前进；"
            f"expected={frozen_head[:12]} current={current_head[:12]}。"
            "请基于最新 main 重新生成、评估并审批候选。"
        )

    _freeze_candidate_head(candidate, changed_files=changed_files, run_id=run_id)
    candidate_head = _fetch_candidate_head(root, candidate)
    if not candidate_head:
        raise CandidateIntegrationError("无法解析候选 HEAD，禁止晋升。")
    if candidate_head == current_head:
        raise CandidateIntegrationError("候选与 main 指向同一提交，禁止空晋升。")
    if not _is_ancestor(root, current_head, candidate_head):
        raise CandidateIntegrationError(
            "candidate_not_descendant: 候选提交不是冻结 main 的后代，禁止自动晋升。"
        )

    current_tree = _git_text(root, "rev-parse", f"{current_head}^{{tree}}")
    candidate_tree = _git_text(root, "rev-parse", f"{candidate_head}^{{tree}}")
    if current_tree == candidate_tree:
        raise CandidateIntegrationError("候选与 main 工作树相同，禁止空晋升。")

    run_label = str(run_id or "").strip()
    _run_git_checked(root, "merge", "--ff-only", candidate_head)
    mechanism = "git_merge_ff"

    commit_sha = _git_text(root, "rev-parse", "HEAD")
    if not commit_sha or commit_sha == current_head:
        raise CandidateIntegrationError("Git 晋升未推进 HEAD，已中止自动合入。")
    result_tree = _git_text(root, "rev-parse", f"{commit_sha}^{{tree}}")
    if result_tree != candidate_tree:
        raise CandidateIntegrationError("晋升后 main 工作树与候选不一致，已中止。")
    if _status_entries(root):
        raise CandidateIntegrationError(
            f"候选提交后主工作区仍有 {len(_status_entries(root))} 项改动，不能声明合入完成。"
        )

    changed_paths = _nul_paths(
        _git_bytes(root, "diff", "--name-only", "-z", current_head, commit_sha)
    )
    if not changed_paths and changed_files:
        changed_paths = _normalized_changed_paths(changed_files)

    manifest = {
        "schemaVersion": 3,
        "mechanism": mechanism,
        "runId": run_label,
        "createdAt": _now_iso(),
        "baseCommit": current_head,
        "candidateCommit": candidate_head,
        "frozenMain": frozen_head,
        "candidateVariantId": variant_id,
        "commitSha": commit_sha,
        "changedFiles": changed_paths,
    }
    manifest_path = _write_manifest(Path(manifest_root), manifest)

    return {
        "status": "committed",
        "mechanism": mechanism,
        "baseCommit": current_head,
        "commitSha": commit_sha,
        "candidateCommit": candidate_head,
        "candidateVariantId": variant_id,
        "changedFiles": changed_paths,
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
    parents = _git_text(root, "rev-list", "--parents", "-n", "1", commit_sha).split()
    revert_args = ["revert", "--no-edit"]
    if len(parents) >= 3:
        revert_args.extend(["-m", "1"])
    revert_args.append(commit_sha)
    result = git_process.run_git(
        revert_args,
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


def _freeze_candidate_head(
    candidate: Path,
    *,
    changed_files: list[dict[str, Any]],
    run_id: str,
) -> None:
    """Commit pending judged changes so promote only reads a Git tree."""

    tracked_dirty = _nul_paths(
        _git_bytes(candidate, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    )
    judged_paths = set(_normalized_changed_paths(changed_files))
    untracked = _nul_paths(
        _git_bytes(candidate, "ls-files", "--others", "--exclude-standard", "-z")
    )
    judged_untracked = [path for path in untracked if path in judged_paths]
    if not tracked_dirty and not judged_untracked:
        return
    if tracked_dirty:
        _run_git_checked(candidate, "add", "-u", "--")
    if judged_untracked:
        _run_git_checked(candidate, "add", "--", *judged_untracked)
    if not _nul_paths(_git_bytes(candidate, "diff", "--cached", "--name-only", "-z")):
        raise CandidateIntegrationError("候选工作区有未提交改动，不在 Git 管辖内，禁止晋升。")
    label = str(run_id or "").strip() or "candidate"
    _run_git_checked(
        candidate,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        f"evolve(supervised): freeze {label}",
    )
    leftover_tracked = _nul_paths(
        _git_bytes(candidate, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    )
    leftover_judged = [
        path
        for path in _nul_paths(
            _git_bytes(candidate, "ls-files", "--others", "--exclude-standard", "-z")
        )
        if path in judged_paths
    ]
    if leftover_tracked or leftover_judged:
        raise CandidateIntegrationError("候选冻结提交后仍有未纳入 Git 的改动，禁止晋升。")


def _fetch_candidate_head(root: Path, candidate: Path) -> str:
    fetch = git_process.run_git(
        [
            "fetch",
            "--no-tags",
            str(candidate),
            "+HEAD:refs/vibelution/supervised-promote",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if fetch.returncode != 0:
        detail = str(fetch.stderr or fetch.stdout or "").strip()
        raise CandidateIntegrationError(f"无法把候选提交取入 main 仓库：{detail or 'fetch failed'}")
    return _git_text(root, "rev-parse", "refs/vibelution/supervised-promote")


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = git_process.run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
