"""Read model for the single Git promotion lane.

Product baseline changes may only land through ``integrate_candidate`` with
``expected_head``. Gym live runs stay evaluation/proposal-only. This module
does not write Git; it projects the latest integration manifest against HEAD.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from core.infrastructure import developer_sandbox, git_process


PROMOTION_LANE = "git_expected_head"
EMPTY_BASELINE: dict[str, Any] = {
    "lane": PROMOTION_LANE,
    "status": "none",
    "commitSha": "",
    "baseCommit": "",
    "runId": "",
    "sourceKind": "",
    "changedFiles": [],
    "committedAt": "",
    "rollbackManifestPath": "",
}


def supervised_integration_manifest_root(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".git" / "vibelution" / "supervised-integration"


def autonomous_integration_manifest_root(project_root: Path) -> Path:
    return (
        developer_sandbox.formal_workspace_path(
            Path(project_root).resolve(),
            "self_evolution",
            "autonomous_loops",
        )
        / "integration_manifests"
    )


def default_promotion_manifest_roots(project_root: Path) -> list[Path]:
    return [
        supervised_integration_manifest_root(project_root),
        autonomous_integration_manifest_root(project_root),
    ]


def build_current_baseline_promotion(
    project_root: Path,
    *,
    current_head: str | None = None,
    manifest_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Return the latest Git promotion and whether it is still HEAD."""

    root = Path(project_root).resolve()
    latest = _latest_manifest(
        list(manifest_roots) if manifest_roots is not None else default_promotion_manifest_roots(root)
    )
    if latest is None:
        return dict(EMPTY_BASELINE)

    payload, source_path = latest
    commit_sha = _text(payload.get("commitSha"))
    head = str(current_head).strip() if current_head is not None else _git_head(root)
    if commit_sha and head and commit_sha == head:
        status = "current"
    elif commit_sha:
        status = "superseded" if head else "unreadable"
    else:
        status = "unreadable"

    changed = payload.get("changedFiles")
    changed_files = (
        [_text(item) for item in changed if _text(item)]
        if isinstance(changed, list)
        else []
    )
    return {
        "lane": PROMOTION_LANE,
        "status": status,
        "commitSha": commit_sha,
        "baseCommit": _text(payload.get("baseCommit") or payload.get("frozenMain")),
        "runId": _text(payload.get("runId")),
        "sourceKind": _source_kind(source_path),
        "changedFiles": changed_files,
        "committedAt": _text(payload.get("committedAt")),
        "rollbackManifestPath": str(source_path),
    }


def _latest_manifest(roots: Sequence[Path]) -> tuple[dict[str, Any], Path] | None:
    latest: tuple[str, str, dict[str, Any], Path] | None = None
    for root in roots:
        directory = Path(root)
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            payload = _read_manifest(path)
            if payload is None:
                continue
            stamp = _text(payload.get("committedAt"))
            commit = _text(payload.get("commitSha"))
            key = (stamp, commit)
            if latest is None or key > (latest[0], latest[1]):
                latest = (stamp, commit, payload, path)
    if latest is None:
        return None
    return latest[2], latest[3]


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if _text(payload.get("status")) and _text(payload.get("status")) != "committed":
        return None
    if not _text(payload.get("commitSha")):
        return None
    return payload


def _source_kind(path: Path) -> str:
    normalized = path.as_posix()
    if "autonomous_loops" in normalized:
        return "autonomous_loop"
    if "supervised-integration" in normalized:
        return "supervised_worktree"
    return "git_integration"


def _git_head(root: Path) -> str:
    result = git_process.run_git(
        ["rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


def _text(value: Any) -> str:
    return str(value or "").strip()
