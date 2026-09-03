from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import git_claim_guard as claim_guard
from scripts import local_quality_gate as gate

INTEGRATION_WAIT_SECONDS = 15.0
INTEGRATION_RETRY_DELAY_SECONDS = 0.5
CLEANUP_RETRY_SECONDS = 2.0
CLEANUP_RETRY_DELAY_SECONDS = 0.2
STALE_RETRY_SCHEMA_VERSION = 1

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
    retry_token_path: str = ""
    retryable: bool = False
    next_action: str = ""
    errors: list[str] = field(default_factory=list)


class ManagedCloseoutError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def _bounded_error(error: BaseException | str) -> str:
    value = str(error).splitlines()[0].strip()
    return value[:300] or type(error).__name__


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def invocation_cwd_is_inside_task(task_worktree: Path | str) -> bool:
    return _is_within(Path.cwd(), Path(task_worktree))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def discover_manifest(context: CloseoutContext) -> Path | None:
    task_id = context.branch.removeprefix("codex/")
    candidate = gate.quality_gate_manifest_path(context.task_root, task_id)
    return candidate if candidate.is_file() else None


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


def acquire_integration_claim(
    context: CloseoutContext,
    *,
    agent_id: str,
    reserve_validation: bool = False,
) -> str:
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
            "15" if reserve_validation else "5",
            "--note",
            (
                "Managed closeout starvation fallback: validation and ff-only merge"
                if reserve_validation
                else "Managed closeout lease: final manifest verification and ff-only merge"
            ),
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


def acquire_integration_claim_with_retry(
    context: CloseoutContext,
    *,
    agent_id: str,
    reserve_validation: bool = False,
    wait_seconds: float = INTEGRATION_WAIT_SECONDS,
) -> str:
    deadline = time.monotonic() + max(0.0, float(wait_seconds))
    while True:
        try:
            return acquire_integration_claim(
                context,
                agent_id=agent_id,
                reserve_validation=reserve_validation,
            )
        except ManagedCloseoutError as error:
            if error.code != "integration_claim_conflict":
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(INTEGRATION_RETRY_DELAY_SECONDS, remaining))


def stale_retry_token_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(f"{manifest_path.name}.stale-retry.json")


def issue_stale_retry_token(
    manifest_path: Path,
    context: CloseoutContext,
    *,
    agent_id: str,
) -> Path:
    path = stale_retry_token_path(manifest_path)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": STALE_RETRY_SCHEMA_VERSION,
                "branch": context.branch,
                "worktree": str(context.task_root),
                "agentId": agent_id,
                "manifestPath": str(manifest_path),
                "issuedAt": _utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def validate_stale_retry_token(
    path: Path | str,
    context: CloseoutContext,
    *,
    agent_id: str,
) -> Path:
    token_path = Path(path).resolve()
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManagedCloseoutError("invalid_stale_retry_token") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != STALE_RETRY_SCHEMA_VERSION
        or payload.get("branch") != context.branch
        or payload.get("agentId") != agent_id
        or Path(str(payload.get("worktree") or "")).resolve() != context.task_root
    ):
        raise ManagedCloseoutError("invalid_stale_retry_token")
    manifest_path = Path(str(payload.get("manifestPath") or "")).resolve()
    if not manifest_path.is_file() or token_path != stale_retry_token_path(manifest_path):
        raise ManagedCloseoutError("invalid_stale_retry_token")
    return token_path


def consume_stale_retry_token(path: Path) -> None:
    try:
        path.unlink()
    except OSError as error:
        raise ManagedCloseoutError("stale_retry_token_consume_failed", str(error)) from error


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


def merge_ff_only(context: CloseoutContext, *, integration_claim_id: str) -> str:
    if gate.git_lines(context.main_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_main")
    target_sha = gate.rev_parse(context.task_root, "HEAD")
    old_sha = gate.rev_parse(context.main_root, "HEAD")
    claim_guard.issue_main_permit(
        context.main_root,
        old_sha=old_sha,
        new_sha=target_sha,
        integration_claim_id=integration_claim_id,
    )
    try:
        completed = gate.run_process(
            ["git", "merge", "--ff-only", context.branch],
            context.main_root,
        )
    finally:
        claim_guard.clear_main_permit(context.main_root)
    if completed.returncode != 0:
        raise ManagedCloseoutError(
            "ff_only_merge_failed",
            _bounded_error(completed.stderr or completed.stdout),
        )
    return target_sha


def resolve_claim_identity(
    context: CloseoutContext,
    *,
    claim_id: str,
    agent_id: str,
) -> tuple[str, str]:
    if claim_id and agent_id:
        return claim_id, agent_id
    binding = claim_guard.read_claim_binding(context.task_root)
    if (
        binding is None
        or binding.branch != context.branch
        or os.path.normcase(str(Path(binding.worktree).resolve()))
        != os.path.normcase(str(context.task_root.resolve()))
    ):
        raise ManagedCloseoutError("claim_identity_required")
    return claim_id or binding.claim_id, agent_id or binding.agent_id


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


def _branch_exists(context: CloseoutContext) -> bool:
    completed = gate.run_process(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{context.branch}"],
        context.main_root,
    )
    return completed.returncode == 0


def _transient_cleanup_failure(completed: subprocess.CompletedProcess[str]) -> bool:
    detail = f"{completed.stderr}\n{completed.stdout}".lower()
    return any(
        marker in detail
        for marker in (
            "access is denied",
            "being used by another process",
            "directory not empty",
            "permission denied",
            "unable to rmdir",
        )
    )


def _remove_worktree_with_retry(context: CloseoutContext) -> subprocess.CompletedProcess[str]:
    deadline = time.monotonic() + CLEANUP_RETRY_SECONDS
    while True:
        completed = gate.run_process(
            ["git", "worktree", "remove", str(context.task_root)],
            context.main_root,
        )
        if completed.returncode == 0 or not _transient_cleanup_failure(completed):
            return completed
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return completed
        time.sleep(min(CLEANUP_RETRY_DELAY_SECONDS, remaining))


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
    task_exists = context.task_root.is_dir()
    if task_exists and gate.git_lines(context.task_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_worktree")
    branch_exists = _branch_exists(context)
    task_head = (
        gate.rev_parse(context.task_root, "HEAD")
        if task_exists
        else gate.rev_parse(context.main_root, context.branch) if branch_exists else ""
    )
    main_head = gate.rev_parse(context.main_root, "HEAD")
    if task_head and not gate.is_ancestor(context.main_root, task_head, main_head):
        raise ManagedCloseoutError("branch_not_merged")
    expected_parent = (context.main_root / ".worktrees").resolve()
    if context.task_root.resolve().parent != expected_parent:
        raise ManagedCloseoutError("unsafe_worktree_path")

    if task_exists:
        for relative in (
            Path(".venv"),
            Path("node_modules"),
            Path("web") / "node_modules",
            Path("挑战杯"),
        ):
            _remove_link_or_junction(context.task_root / relative)
        if invocation_cwd_is_inside_task(context.task_root):
            os.chdir(context.main_root)
        removed = _remove_worktree_with_retry(context)
        if removed.returncode != 0:
            raise ManagedCloseoutError(
                "worktree_remove_failed",
                _bounded_error(removed.stderr or removed.stdout),
            )
    if branch_exists:
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


def resolve_cleanup_context(
    task_worktree: Path | str,
    *,
    branch: str,
    base: str = "main",
) -> CloseoutContext:
    task_root = Path(task_worktree).resolve()
    if task_root.parent.name != ".worktrees":
        raise ManagedCloseoutError("unsafe_worktree_path")
    main_root = task_root.parent.parent.resolve()
    if gate.current_branch(main_root) != base:
        raise ManagedCloseoutError("invalid_main_worktree")
    if gate.git_lines(main_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_main")
    if not branch.startswith("codex/") or branch == "codex/":
        raise ManagedCloseoutError("invalid_task_branch")
    if task_root.is_dir():
        if gate.repository_root(task_root).resolve() != task_root:
            raise ManagedCloseoutError("unsafe_worktree_path")
        if gate.current_branch(task_root) != branch:
            raise ManagedCloseoutError("invalid_task_branch")
    return CloseoutContext(main_root=main_root, task_root=task_root, branch=branch)


def run_cleanup_only(
    task_worktree: Path | str,
    *,
    branch: str,
    agent_id: str,
    base: str = "main",
) -> ManagedCloseoutResult:
    try:
        context = resolve_cleanup_context(task_worktree, branch=branch, base=base)
        cleanup_task_resources(context, agent_id=agent_id)
        prune_coordination(context)
    except (OSError, RuntimeError, ValueError) as error:
        return ManagedCloseoutResult(
            status="merged_cleanup_pending",
            exit_code=2,
            merged=True,
            retryable=True,
            next_action="rerun_cleanup_only_from_main",
            errors=[_bounded_error(error)],
        )
    return ManagedCloseoutResult(
        status="merged_clean",
        exit_code=0,
        merged=True,
    )


def run_managed_closeout(
    task_worktree: Path | str,
    *,
    claim_id: str = "",
    agent_id: str = "",
    base: str = "main",
    manifest_path: Path | str | None = None,
    reserve_integration: bool = False,
    stale_retry_token: Path | str | None = None,
    integration_wait_seconds: float = INTEGRATION_WAIT_SECONDS,
) -> ManagedCloseoutResult:
    try:
        context = resolve_context(task_worktree, base=base)
        claim_id, agent_id = resolve_claim_identity(
            context,
            claim_id=claim_id,
            agent_id=agent_id,
        )
        validate_development_claim(context, claim_id=claim_id, agent_id=agent_id)
    except (OSError, RuntimeError, ValueError) as error:
        return ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            errors=[_bounded_error(error)],
        )

    explicit_manifest = manifest_path is not None
    resolved_manifest = (
        Path(manifest_path)
        if explicit_manifest
        else discover_manifest(context)
    )
    manifest_path_text = str(resolved_manifest or "")
    integration_claim_id = ""
    validated_retry_token: Path | None = None
    if reserve_integration:
        try:
            if stale_retry_token is None:
                raise ManagedCloseoutError("stale_retry_token_required")
            validated_retry_token = validate_stale_retry_token(
                stale_retry_token,
                context,
                agent_id=agent_id,
            )
            integration_claim_id = acquire_integration_claim_with_retry(
                context,
                agent_id=agent_id,
                reserve_validation=True,
                wait_seconds=integration_wait_seconds,
            )
            consume_stale_retry_token(validated_retry_token)
        except ManagedCloseoutError as error:
            return ManagedCloseoutResult(
                status=(
                    "integration_claim_conflict"
                    if error.code == "integration_claim_conflict"
                    else "failed"
                ),
                exit_code=1,
                manifest_path=manifest_path_text,
                retryable=error.code == "integration_claim_conflict",
                next_action=(
                    "retry_reserve_with_same_token"
                    if error.code == "integration_claim_conflict"
                    else "use_stale_retry_token_from_prior_result"
                ),
                errors=[_bounded_error(error)],
            )

    validation_result: ManagedCloseoutResult | None = None
    try:
        manifest_preverified = False
        if resolved_manifest is not None and not explicit_manifest:
            verified = gate.verify_manifest(
                resolved_manifest,
                context.task_root,
                base,
            )
            if verified.outcome == "passed":
                manifest_preverified = True
            else:
                resolved_manifest = None
                manifest_path_text = ""

        if resolved_manifest is None:
            closeout = gate.run_closeout(context.task_root, base, claim_id)
            resolved_manifest = closeout.manifest_path
            manifest_path_text = str(resolved_manifest or "")
            if closeout.outcome != "passed" or resolved_manifest is None:
                validation_result = ManagedCloseoutResult(
                    status="validation_failed",
                    exit_code=1,
                    manifest_path=manifest_path_text,
                    errors=[str(closeout.outcome)],
                )

        if validation_result is None and not manifest_preverified:
            verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
            if verified.outcome != "passed":
                validation_result = ManagedCloseoutResult(
                    status="validation_failed",
                    exit_code=1,
                    manifest_path=manifest_path_text,
                    errors=[str(verified.outcome)],
                )
    except (OSError, RuntimeError, ValueError) as error:
        validation_result = ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            manifest_path=manifest_path_text,
            errors=[_bounded_error(error)],
        )

    if validation_result is not None:
        if (
            validation_result.errors == ["stale_main"]
            and resolved_manifest is not None
        ):
            try:
                retry_token = issue_stale_retry_token(
                    resolved_manifest,
                    context,
                    agent_id=agent_id,
                )
                validation_result.retry_token_path = str(retry_token)
                validation_result.retryable = True
                validation_result.next_action = "sync_main_then_reserve_with_token"
            except OSError as error:
                validation_result.errors.append(
                    f"stale_retry_token_pending: {_bounded_error(error)}"
                )
        if integration_claim_id:
            try:
                release_claim(
                    context,
                    integration_claim_id,
                    status="released",
                    reason="reserved validation did not pass",
                )
            except (OSError, RuntimeError, ValueError) as error:
                validation_result.errors.append(
                    f"integration_release_pending: {_bounded_error(error)}"
                )
                validation_result.status = "failed"
        return validation_result

    if not integration_claim_id:
        try:
            integration_claim_id = acquire_integration_claim_with_retry(
                context,
                agent_id=agent_id,
                wait_seconds=integration_wait_seconds,
            )
        except ManagedCloseoutError as error:
            return ManagedCloseoutResult(
                status=(
                    "integration_claim_conflict"
                    if error.code == "integration_claim_conflict"
                    else "failed"
                ),
                exit_code=1,
                manifest_path=manifest_path_text,
                retryable=(
                    error.code == "integration_claim_conflict" and bool(manifest_path_text)
                ),
                next_action=(
                    "retry_with_manifest"
                    if error.code == "integration_claim_conflict" and manifest_path_text
                    else ""
                ),
                errors=[_bounded_error(error)],
            )

    integration_released = False
    merge_sha = ""
    result = ManagedCloseoutResult(status="failed", exit_code=1)
    try:
        verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
        if verified.outcome != "passed":
            retry_token_path = ""
            retryable = False
            next_action = ""
            if verified.outcome == "stale_main":
                retry_token = issue_stale_retry_token(
                    resolved_manifest,
                    context,
                    agent_id=agent_id,
                )
                retry_token_path = str(retry_token)
                retryable = True
                next_action = "sync_main_then_reserve_with_token"
            result = ManagedCloseoutResult(
                status="validation_failed",
                exit_code=1,
                manifest_path=manifest_path_text,
                retry_token_path=retry_token_path,
                retryable=retryable,
                next_action=next_action,
                errors=[str(verified.outcome)],
            )
        else:
            merge_sha = merge_ff_only(
                context,
                integration_claim_id=integration_claim_id,
            )
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
                retryable=bool(cleanup_errors),
                next_action=("run_cleanup_only_from_main" if cleanup_errors else ""),
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
            retryable=bool(merge_sha),
            next_action=("run_cleanup_only_from_main" if merge_sha else ""),
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
                if result.merged:
                    result.retryable = True
                    result.next_action = "run_cleanup_only_from_main"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, ff-only merge, and safely clean one Vibelution task worktree."
    )
    parser.add_argument("--task-worktree", type=Path, required=True)
    parser.add_argument("--claim-id", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--base", default="main")
    parser.add_argument("--branch", default="")
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Resume safe local cleanup after a merge already succeeded.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Reuse an already passed manifest for this exact task HEAD and main SHA.",
    )
    parser.add_argument(
        "--reserve-integration",
        action="store_true",
        help="After stale_main, reserve integration/main during the one validation retry.",
    )
    parser.add_argument(
        "--stale-retry-token",
        type=Path,
        help="One-use retry token returned by a prior stale_main result.",
    )
    parser.add_argument(
        "--integration-wait-seconds",
        type=float,
        default=INTEGRATION_WAIT_SECONDS,
        help="Bounded wait for the short integration lease without rerunning validation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if invocation_cwd_is_inside_task(args.task_worktree):
        result = ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            retryable=True,
            next_action="rerun_from_main",
            errors=["task_worktree_cannot_be_invocation_cwd"],
        )
    elif args.cleanup_only:
        if not args.agent_id:
            result = ManagedCloseoutResult(
                status="failed",
                exit_code=1,
                errors=["agent_id_required_for_cleanup_only"],
            )
        elif not args.branch:
            result = ManagedCloseoutResult(
                status="failed",
                exit_code=1,
                errors=["branch_required_for_cleanup_only"],
            )
        else:
            result = run_cleanup_only(
                args.task_worktree,
                branch=args.branch,
                agent_id=args.agent_id,
                base=args.base,
            )
    else:
        result = run_managed_closeout(
            args.task_worktree,
            claim_id=args.claim_id,
            agent_id=args.agent_id,
            base=args.base,
            manifest_path=args.manifest,
            reserve_integration=args.reserve_integration,
            stale_retry_token=args.stale_retry_token,
            integration_wait_seconds=args.integration_wait_seconds,
        )
    print(json.dumps(asdict(result), ensure_ascii=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
