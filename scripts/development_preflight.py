#!/usr/bin/env python3
"""Read-only development scope and Launcher approval handoff; never execute lifecycle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.infrastructure.branch_workspace import (  # noqa: E402
    BranchWorkspaceError,
    list_branch_instances,
    resolve_branch_workspace,
)

OPERATIONS = ("status", "start", "stop", "restart")


def _git(root: Path, *args: str) -> str:
    # Only fixed read operations call this helper; never accept a command from input.
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("Git identity could not be verified.")
    return result.stdout.strip()


def normalize_files(files: Sequence[str]) -> list[str]:
    normalized = []
    for value in files:
        name = value.replace("\\", "/")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ":" in name or ".." in path.parts:
            raise ValueError("Files must be checkout-relative paths without traversal.")
        if str(path) == ".":
            raise ValueError("Specify individual files rather than the whole checkout.")
        normalized.append(str(path))
    return sorted(set(normalized))


def refresh_requirement(files: Sequence[str]) -> str:
    if not files:
        return "review_required"
    kinds = []
    for name in files:
        if name.endswith(".md") or name.startswith("tests/") or name == "scripts/development_preflight.py":
            kinds.append("none")
        elif name.startswith("web/"):
            kinds.append("before_browser_acceptance")
        elif name.startswith(("core/", "config/", "desktop/")) or name == "requirements.txt":
            kinds.append("before_runtime_acceptance")
        else:
            kinds.append("review_required")
    # This is a conservative triage hint, not the authoritative refresh decision.
    for kind in ("review_required", "before_runtime_acceptance", "before_browser_acceptance"):
        if kind in kinds:
            return kind
    return "none"


def select_instance(snapshot: dict[str, Any], instance_id: str, operation: str) -> dict[str, Any]:
    if operation not in OPERATIONS:
        raise ValueError("Unsupported operation.")
    matches = [item for item in snapshot.get("items", []) if item.get("id") == instance_id]
    if len(matches) != 1:
        raise ValueError("The exact registered instance must be unambiguous.")
    item = matches[0]
    if not item.get("checkedOut") or not item.get("path") or not Path(item["path"]).is_dir():
        raise ValueError("The instance needs an existing registered checkout.")
    if operation != "status" and (
        item.get("kind") != "worktree" or not str(item.get("branch", "")).startswith("codex/")
    ):
        raise ValueError("Lifecycle handoff is restricted to isolated codex/* worktrees.")
    if operation != "status" and instance_id == "main":
        raise ValueError("Main lifecycle handoff is not supported.")
    return item


def build_report(project: Path, instance_id: str, operation: str, files: Sequence[str]) -> dict[str, Any]:
    files = normalize_files(files)
    layout = resolve_branch_workspace(project)
    snapshot = list_branch_instances(layout.integration_root)
    target = select_instance(snapshot, instance_id, operation)
    root = Path(target["path"]).resolve()
    # Recheck Git identity rather than treating an earlier projection as authorization.
    target_layout = resolve_branch_workspace(root)
    if target_layout.integration_root != layout.integration_root or target_layout.worktree_root != root:
        raise ValueError("Target checkout identity changed; inspect again.")
    branch = _git(root, "branch", "--show-current")
    if branch != target["branch"]:
        raise ValueError("Target branch changed; inspect again.")
    if any(not (root / name).resolve().is_relative_to(root) for name in files):
        raise ValueError("File scope resolves outside the checkout.")
    head = _git(root, "rev-parse", "HEAD")
    isolated = target["kind"] == "worktree" and branch.startswith("codex/") and root != layout.integration_root
    target_key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    scratch = Path(tempfile.gettempdir()).resolve() / "Vibelution-development" / target_key
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "readOnly": True,
        "executionAttempted": False,
        "target": {"instanceId": instance_id, "workspaceRoot": str(root), "branch": branch, "head": head},
        "development": {
            "isolationSatisfied": isolated,
            "writeScope": files,
            "claimPreflightRequired": True,
            "suggestedWritableRoots": [str(root), str(scratch)] if isolated else [],
            "readOnlyDependencies": [str(layout.integration_root / ".venv"), str(root / "web" / "node_modules")],
            "pathsCreated": False,
        },
        "runtime": {
            "evidence": "registry_projection_only",
            "registryAlive": target.get("alive") is True,
            "registryPort": target.get("port", 0),
            "healthVerified": False,
            "runningRevisionVerified": False,
            "browserAcceptanceVerified": False,
        },
        "verification": {
            "refreshHint": refresh_requirement(files),
            "manifestAuthority": "scripts/task_closeout.py",
            "reuseOnlyAfterContentAndValidationSurfaceCheck": True,
        },
        "approval": {
            "effectiveHostPolicy": "not_observable_by_this_tool",
            "approvalGranted": False,
            "configChanged": False,
            "ifHostPolicyNever": "A forbidden action cannot be approved in this session; do not retry through another tool.",
        },
    }
    if operation != "status":
        report["lifecycleHandoff"] = {
            "operation": operation,
            "requiresHostApproval": True,
            "requiresLauncherRevalidation": True,
            "preflightIsNotAuthorization": True,
            "authority": "Electron main Launcher IPC",
            "request": {
                "schemaVersion": 1,
                "path": f"branch-instances/{operation}",
                "init": {"method": "POST", "body": {"instanceId": instance_id}},
            },
            "afterDispatch": "Observe native commandId/generation and settlement; a lost response does not authorize redispatch.",
        }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--operation", choices=OPERATIONS, default="status", help="Prepare a handoff only; never execute it.")
    parser.add_argument("--files", nargs="*", default=[])
    args = parser.parse_args(argv)
    try:
        report = build_report(args.project, args.instance_id, args.operation, args.files)
    except (BranchWorkspaceError, OSError, ValueError, subprocess.TimeoutExpired):
        # Do not echo input/error text that could contain arbitrary payloads or secrets.
        print(json.dumps({"schemaVersion": 1, "readOnly": True, "executionAttempted": False,
                          "error": "preflight_failed", "message": "Check the registered instance, Git identity and relative file scope."}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
