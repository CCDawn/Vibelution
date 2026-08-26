from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import local_quality_gate as gate

CloseoutStatus = Literal[
    "merged_clean",
    "merged_cleanup_pending",
    "integration_claim_conflict",
    "validation_failed",
    "failed",
]


@dataclass(frozen=True)
class CloseoutContext:
    main_root: Path
    task_root: Path
    branch: str


@dataclass
class ManagedCloseoutResult:
    status: CloseoutStatus
    exit_code: int
    merged: bool = False
    merge_sha: str = ""
    manifest_path: str = ""
    errors: list[str] = field(default_factory=list)


class ManagedCloseoutError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _bounded_error(error: BaseException | str) -> str:
    value = str(error).splitlines()[0].strip()
    return value[:300] or type(error).__name__


def resolve_context(task_worktree: Path | str, *, base: str = "main") -> CloseoutContext:
    task_root = gate.repository_root(Path(task_worktree)).resolve()
    branch = gate.current_branch(task_root)
    if not branch or branch == base or not branch.startswith("codex/"):
        raise ManagedCloseoutError("invalid_task_branch")
    main_root = gate.main_worktree(task_root, base).resolve()
    if task_root == main_root or gate.current_branch(main_root) != base:
        raise ManagedCloseoutError("invalid_main_worktree")
    if gate.git_lines(main_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_main")
    if gate.git_lines(task_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_worktree")
    expected_parent = (main_root / ".worktrees").resolve()
    if task_root.parent != expected_parent:
        raise ManagedCloseoutError(
            "unsafe_worktree_path",
            f"managed cleanup requires a direct child of {expected_parent}",
        )
    return CloseoutContext(main_root=main_root, task_root=task_root, branch=branch)


def _coordination_script() -> Path:
    for candidate in gate.GUARD_SCRIPT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise ManagedCloseoutError("coordination_unavailable")


def _coordination_call(context: CloseoutContext, *arguments: str) -> dict[str, object]:
    completed = gate.run_process(
        [sys.executable, str(_coordination_script()), str(context.main_root), *arguments, "--json"],
        context.main_root,
    )
    if completed.returncode != 0:
        summary = completed.stderr.strip() or completed.stdout.strip()
        try:
            failure = json.loads(completed.stdout)
        except json.JSONDecodeError:
            failure = None
        if isinstance(failure, dict) and failure.get("conflicts"):
            raise ManagedCloseoutError("coordination_conflict", _bounded_error(summary))
        raise ManagedCloseoutError("coordination_failed", _bounded_error(summary))
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ManagedCloseoutError("coordination_invalid_response") from error
    if not isinstance(payload, dict):
        raise ManagedCloseoutError("coordination_invalid_response")
    return payload


def validate_development_claim(
    context: CloseoutContext,
    *,
    claim_id: str,
    agent_id: str,
) -> None:
    status = _coordination_call(context, "status")
    claims = status.get("claims")
    claim = next(
        (
            item
            for item in claims
            if isinstance(item, dict) and item.get("id") == claim_id
        ),
        None,
    ) if isinstance(claims, list) else None
    if claim is None or claim.get("status") not in {"active", "ready"}:
        raise ManagedCloseoutError("invalid_development_claim")
    if claim.get("agentId") != agent_id:
        raise ManagedCloseoutError("invalid_claim_owner")


def acquire_integration_claim(context: CloseoutContext, *, agent_id: str) -> str:
    try:
        payload = _coordination_call(
            context,
            "claim",
            "--lane",
            "integration",
            "--scope",
            "integration/main",
            "--agent-id",
            agent_id,
            "--task",
            f"Integrate {context.branch}",
            "--status",
            "active",
            "--ttl-minutes",
            "5",
            "--note",
            "Managed closeout lease: final manifest verification and ff-only merge",
        )
    except ManagedCloseoutError as error:
        if error.code == "coordination_conflict":
            raise ManagedCloseoutError("integration_claim_conflict", str(error)) from error
        raise
    claim = payload.get("claim")
    claim_id = str(claim.get("id") or "") if isinstance(claim, dict) else ""
    if not claim_id:
        raise ManagedCloseoutError("integration_claim_conflict")
    return claim_id


def release_claim(
    context: CloseoutContext,
    claim_id: str,
    *,
    status: Literal["released", "completed", "blocked"],
    reason: str,
) -> None:
    _coordination_call(
        context,
        "release",
        "--claim-id",
        claim_id,
        "--status",
        status,
        "--reason",
        reason,
    )


def complete_agent(context: CloseoutContext, *, agent_id: str, merge_sha: str) -> None:
    status = _coordination_call(context, "status")
    claims = status.get("claims")
    remaining = [
        item
        for item in claims
        if isinstance(item, dict)
        and item.get("agentId") == agent_id
        and item.get("status") in {"active", "ready", "yielded"}
    ] if isinstance(claims, list) else []
    if remaining:
        raise ManagedCloseoutError("agent_has_other_active_claims")
    _coordination_call(
        context,
        "complete",
        "--agent-id",
        agent_id,
        "--summary",
        f"Managed closeout merged {context.branch} at {merge_sha}",
    )


def prune_coordination(context: CloseoutContext) -> None:
    _coordination_call(context, "prune")


def merge_ff_only(context: CloseoutContext) -> str:
    if gate.git_lines(context.main_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_main")
    target_sha = gate.rev_parse(context.task_root, "HEAD")
    completed = gate.run_process(
        ["git", "merge", "--ff-only", context.branch],
        context.main_root,
    )
    if completed.returncode != 0:
        raise ManagedCloseoutError(
            "ff_only_merge_failed",
            _bounded_error(completed.stderr or completed.stdout),
        )
    return target_sha


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _remove_link_or_junction(path: Path) -> None:
    if not _is_link_or_junction(path):
        return
    if path.is_dir():
        os.rmdir(path)
    else:
        path.unlink()


def ensure_cleanup_unowned(context: CloseoutContext, *, agent_id: str) -> None:
    status = _coordination_call(context, "status")
    agents = status.get("agents")
    task_root = os.path.normcase(str(context.task_root.resolve()))
    conflicting = [
        item
        for item in agents
        if isinstance(item, dict)
        and item.get("id") != agent_id
        and item.get("state") in {"active", "paused"}
        and (
            item.get("branch") == context.branch
            or (
                item.get("worktree")
                and os.path.normcase(str(Path(str(item["worktree"])).resolve())) == task_root
            )
        )
    ] if isinstance(agents, list) else []
    if conflicting:
        raise ManagedCloseoutError("task_resources_still_owned")


def cleanup_task_resources(context: CloseoutContext, *, agent_id: str) -> None:
    ensure_cleanup_unowned(context, agent_id=agent_id)
    if gate.git_lines(context.task_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_worktree")
    task_head = gate.rev_parse(context.task_root, "HEAD")
    main_head = gate.rev_parse(context.main_root, "HEAD")
    if not gate.is_ancestor(context.main_root, task_head, main_head):
        raise ManagedCloseoutError("branch_not_merged")
    expected_parent = (context.main_root / ".worktrees").resolve()
    if context.task_root.resolve().parent != expected_parent:
        raise ManagedCloseoutError("unsafe_worktree_path")

    for relative in (
        Path(".venv"),
        Path("node_modules"),
        Path("web") / "node_modules",
        Path("挑战杯"),
    ):
        _remove_link_or_junction(context.task_root / relative)

    removed = gate.run_process(
        ["git", "worktree", "remove", str(context.task_root)],
        context.main_root,
    )
    if removed.returncode != 0:
        raise ManagedCloseoutError(
            "worktree_remove_failed",
            _bounded_error(removed.stderr or removed.stdout),
        )
    branch_deleted = gate.run_process(
        ["git", "branch", "-d", context.branch],
        context.main_root,
    )
    if branch_deleted.returncode != 0:
        raise ManagedCloseoutError(
            "branch_delete_failed",
            _bounded_error(branch_deleted.stderr or branch_deleted.stdout),
        )
    pruned = gate.run_process(["git", "worktree", "prune"], context.main_root)
    if pruned.returncode != 0:
        raise ManagedCloseoutError(
            "worktree_prune_failed",
            _bounded_error(pruned.stderr or pruned.stdout),
        )


def run_managed_closeout(
    task_worktree: Path | str,
    *,
    claim_id: str,
    agent_id: str,
    base: str = "main",
    manifest_path: Path | str | None = None,
) -> ManagedCloseoutResult:
    try:
        context = resolve_context(task_worktree, base=base)
        validate_development_claim(context, claim_id=claim_id, agent_id=agent_id)
    except (OSError, RuntimeError, ValueError) as error:
        return ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            errors=[_bounded_error(error)],
        )

    resolved_manifest = Path(manifest_path) if manifest_path is not None else None
    manifest_path_text = str(resolved_manifest or "")
    try:
        if resolved_manifest is None:
            closeout = gate.run_closeout(context.task_root, base, claim_id)
            resolved_manifest = closeout.manifest_path
            manifest_path_text = str(resolved_manifest or "")
            if closeout.outcome != "passed" or resolved_manifest is None:
                return ManagedCloseoutResult(
                    status="validation_failed",
                    exit_code=1,
                    manifest_path=manifest_path_text,
                    errors=[str(closeout.outcome)],
                )

        verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
        if verified.outcome != "passed":
            return ManagedCloseoutResult(
                status="validation_failed",
                exit_code=1,
                manifest_path=manifest_path_text,
                errors=[str(verified.outcome)],
            )
    except (OSError, RuntimeError, ValueError) as error:
        return ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            manifest_path=manifest_path_text,
            errors=[_bounded_error(error)],
        )

    try:
        integration_claim_id = acquire_integration_claim(context, agent_id=agent_id)
    except ManagedCloseoutError as error:
        return ManagedCloseoutResult(
            status=(
                "integration_claim_conflict"
                if error.code == "integration_claim_conflict"
                else "failed"
            ),
            exit_code=1,
            manifest_path=manifest_path_text,
            errors=[_bounded_error(error)],
        )

    integration_released = False
    merge_sha = ""
    result = ManagedCloseoutResult(status="failed", exit_code=1)
    try:
        verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
        if verified.outcome != "passed":
            result = ManagedCloseoutResult(
                status="validation_failed",
                exit_code=1,
                manifest_path=manifest_path_text,
                errors=[str(verified.outcome)],
            )
        else:
            merge_sha = merge_ff_only(context)
            release_claim(
                context,
                claim_id,
                status="completed",
                reason=f"merged to {base} at {merge_sha}",
            )
            release_claim(
                context,
                integration_claim_id,
                status="completed",
                reason=f"ff-only merge completed at {merge_sha}",
            )
            integration_released = True
            cleanup_errors: list[str] = []
            try:
                cleanup_task_resources(context, agent_id=agent_id)
            except (OSError, RuntimeError, ValueError) as error:
                cleanup_errors.append(_bounded_error(error))
            try:
                complete_agent(context, agent_id=agent_id, merge_sha=merge_sha)
                prune_coordination(context)
            except (OSError, RuntimeError, ValueError) as error:
                cleanup_errors.append(_bounded_error(error))
            result = ManagedCloseoutResult(
                status="merged_cleanup_pending" if cleanup_errors else "merged_clean",
                exit_code=2 if cleanup_errors else 0,
                merged=True,
                merge_sha=merge_sha,
                manifest_path=manifest_path_text,
                errors=cleanup_errors,
            )
    except (OSError, RuntimeError, ValueError) as error:
        if merge_sha:
            status: CloseoutStatus = "merged_cleanup_pending"
            exit_code = 2
        else:
            status = "failed"
            exit_code = 1
        result = ManagedCloseoutResult(
            status=status,
            exit_code=exit_code,
            merged=bool(merge_sha),
            merge_sha=merge_sha,
            manifest_path=manifest_path_text,
            errors=[_bounded_error(error)],
        )
    finally:
        if not integration_released:
            try:
                release_claim(
                    context,
                    integration_claim_id,
                    status="released" if not merge_sha else "completed",
                    reason="managed closeout released its integration lease",
                )
            except (OSError, RuntimeError, ValueError) as error:
                result.errors.append(f"integration_release_pending: {_bounded_error(error)}")
                result.status = "merged_cleanup_pending" if result.merged else "failed"
                result.exit_code = 2 if result.merged else 1
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, ff-only merge, and safely clean one Vibelution task worktree."
    )
    parser.add_argument("--task-worktree", type=Path, required=True)
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Reuse an already passed manifest for this exact task HEAD and main SHA.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_managed_closeout(
        args.task_worktree,
        claim_id=args.claim_id,
        agent_id=args.agent_id,
        base=args.base,
        manifest_path=args.manifest,
    )
    print(json.dumps(asdict(result), ensure_ascii=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
