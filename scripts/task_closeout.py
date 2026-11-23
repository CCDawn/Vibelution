from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.platform_version.ledger import resolve_ledger_path
from scripts import git_claim_guard as claim_guard
from scripts import git_hook_install as hook_install
from scripts import local_quality_gate as gate

INTEGRATION_WAIT_SECONDS = 15.0
INTEGRATION_RETRY_DELAY_SECONDS = 0.5
CLEANUP_RETRY_SECONDS = 2.0
CLEANUP_RETRY_DELAY_SECONDS = 0.2
STALE_RETRY_SCHEMA_VERSION = 1
# Exit code for "the merge is authoritative but publishing the version
# projection (sync commit, tag, release or push) failed". Distinct from 2
# (cleanup pending) so callers can tell merge-ok/publish-failed from
# merge-failed without parsing the JSON body.
MERGED_PUBLISH_PENDING_EXIT_CODE = 3
# Upper bound for the per-file lines attached to a dirty_main outcome. A
# stray session can leave dozens of edits in main; the attribution must stay
# bounded evidence, not an unbounded dump of ``git status``.
DIRTY_MAIN_FILE_LIMIT = 20

# Validation outcomes whose next step is one specific, mechanical action. Naming
# it here keeps the operator or agent from rediscovering the workflow from the
# docs: a missing or stale reuse-research record is fixed by recording it for
# this branch and re-running the same closeout, not by editing code.
RECOVERABLE_VALIDATION_ACTIONS = {
    "reuse_research_missing": "record_reuse_research_evidence",
    "reuse_research_invalid": "fix_reuse_research_evidence",
    "validation_node_modules_source_missing": "install_node_modules_in_main_checkout",
    "validation_node_modules_link_failed": "create_node_modules_link_manually",
}

# Task-owned disposable paths removed before the worktree itself.  The
# node_modules entries are junctions the closeout preflight creates (or that
# older tasks created by hand); they must be unlinked first so the worktree
# removal never descends into the shared main checkout's real install.
TASK_OWNED_EPHEMERAL_PATHS = (
    Path(".venv"),
    Path("node_modules"),
    Path("web") / "node_modules",
    Path("desktop") / "electron" / "node_modules",
    Path("挑战杯"),
)

CloseoutStatus = Literal[
    "merged_clean",
    "merged_cleanup_pending",
    "merged_publish_pending",
    "integration_claim_conflict",
    "validation_failed",
    "failed",
]


@dataclass(frozen=True)
class CloseoutContext:
    main_root: Path
    task_root: Path
    branch: str
    base: str = "main"


@dataclass(frozen=True)
class FailureDetail:
    """One failed validation command, surfaced at the closeout result top level."""

    code: str
    command_kind: str
    argv0: str
    exit_code: int
    summary: str


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
    failures: list[FailureDetail] = field(default_factory=list)
    # Non-blocking observations: version projection consistency findings that
    # must never stop the merge by themselves.
    warnings: list[str] = field(default_factory=list)
    # Post-merge version automation. ``versionSync`` carries the
    # settle+project+tag+release outcome, ``push`` the independent push
    # outcome; a failed push never invalidates the merged state above.
    # When publish did not run, these carry ``{"ok": False, "skipped_reason":
    # ...}`` instead of being silently empty, so the publish debt stays
    # visible on every non-clean merged result.
    versionSync: dict[str, Any] = field(default_factory=dict)
    push: dict[str, Any] = field(default_factory=dict)


class ManagedCloseoutError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        # ``dirty_main`` carries bounded attribution evidence here so the
        # ``errors`` envelope can stay exactly ``["dirty_main", ...lines]``
        # while the raised error itself explains who is holding main dirty.
        self.detail_lines: list[str] = []
        self.next_action = ""


def command_failure_details(code: str, commands: Sequence[Any]) -> list[FailureDetail]:
    """Return structured details for every failed command in one gate result.

    ``errors`` stays a human-readable string list for compatibility, but it only
    carries the coarse outcome (``failed``). Callers that need to know which
    command failed and why should read ``failures`` instead of opening the
    manifest and guessing the field name.
    """

    details: list[FailureDetail] = []
    for command in commands or ():
        status = str(getattr(command, "status", "") or "")
        if status == "passed":
            continue
        argv = list(getattr(command, "argv", None) or ())
        exit_code = int(getattr(command, "exit_code", 0) or 0)
        details.append(
            FailureDetail(
                code=code,
                command_kind=str(getattr(command, "kind", "") or ""),
                argv0=str(argv[0]) if argv else "",
                exit_code=exit_code,
                summary=gate.bounded_failure_summary(
                    str(getattr(command, "failure_summary", "") or "")
                ),
            )
        )
    return details


def _bounded_error(error: BaseException | str) -> str:
    value = str(error).splitlines()[0].strip()
    return value[:300] or type(error).__name__


@dataclass(frozen=True)
class DirtyMainAttribution:
    """Bounded evidence for one dirty_main outcome: what changed, when, who.

    ``file_lines`` are ready-to-print ``dirty_main_file:`` entries (path plus
    mtime) capped at ``DIRTY_MAIN_FILE_LIMIT``; ``owner_lines`` name the active
    claims whose scopes touch the dirty paths; ``next_action`` is the one
    human-readable recovery sentence naming the suspected owner.
    """

    file_lines: tuple[str, ...]
    owner_lines: tuple[str, ...]
    next_action: str


def _dirty_main_entries(main_root: Path) -> list[tuple[str, str]]:
    """Parse ``git status --porcelain -z`` into bounded ``(status, path)`` pairs.

    The ``-z`` format separates entries with NULs and, for rename/copy entries,
    records the new path first and the original path as a second NUL-separated
    field; the original path is skipped so only real worktree paths survive.
    """

    completed = gate.run_process(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        main_root,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git status failed")
    entries: list[tuple[str, str]] = []
    tokens = completed.stdout.split("\0")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        status = token[:2]
        path = token[3:] if len(token) > 3 else token
        if status and status[0] in {"R", "C"} and index < len(tokens):
            index += 1
        entries.append((status, gate.normalize_path(path)))
    return entries


def _dirty_main_mtime_line(main_root: Path, path: str) -> str:
    try:
        stamp = os.stat(main_root / path).st_mtime
    except OSError:
        return "mtime=unavailable"
    return (
        "mtime="
        + datetime.fromtimestamp(stamp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _suspected_dirty_main_owners(
    context: CloseoutContext,
    paths: Sequence[str],
) -> tuple[str, ...]:
    """Name active claims whose scopes touch the dirty paths (best effort).

    The claim table is read through the same coordination ``status`` call the
    closeout already uses for claim validation; any failure to read it must not
    mask the underlying dirty_main outcome, so every error collapses to "no
    suspected owner".
    """

    if not paths:
        return ()
    try:
        status = _coordination_call(context, "status")
    except (OSError, RuntimeError, ValueError):
        return ()
    claims = status.get("claims") if isinstance(status.get("claims"), list) else []
    agents = status.get("agents") if isinstance(status.get("agents"), list) else []
    agents_by_id = {
        str(item.get("id")): item
        for item in agents
        if isinstance(item, dict) and item.get("id")
    }
    owners: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("status") not in {
            "active",
            "ready",
        }:
            continue
        raw_scopes = claim.get("scopes")
        scopes = (
            [str(scope) for scope in raw_scopes if isinstance(scope, str)]
            if isinstance(raw_scopes, list)
            else []
        )
        matched = [
            path for path in paths if any(gate.scope_covers(scope, path) for scope in scopes)
        ]
        if not matched:
            continue
        agent = agents_by_id.get(str(claim.get("agentId") or ""), {})
        branch = str(agent.get("branch") or "") if isinstance(agent, dict) else ""
        description = (
            f"agent {claim.get('agentId') or 'unknown'}"
            + (f" (branch {branch})" if branch else "")
            + f" via claim {claim.get('id') or 'unknown'} covering "
            f"{len(matched)}/{len(paths)} dirty paths, e.g. {matched[0]}"
        )
        owners.append(description)
    return tuple(owners[:3])


def describe_dirty_main(context: CloseoutContext) -> DirtyMainAttribution:
    """Attribute an unexpectedly dirty main checkout to its likely owner.

    The 2026-09 incidents showed a foreign session holding main dirty for 20
    minutes with nobody knowing whom to ask; this turns the raw ``dirty_main``
    outcome into evidence (file list with mtimes) plus one actionable sentence.
    """

    entries = _dirty_main_entries(context.main_root)
    shown = entries[:DIRTY_MAIN_FILE_LIMIT]
    file_lines = tuple(
        f"dirty_main_file: {status or '??'} {path} "
        f"({_dirty_main_mtime_line(context.main_root, path)})"
        for status, path in shown
    )
    hidden = len(entries) - len(shown)
    if hidden > 0:
        file_lines += (f"dirty_main_file: ...and {hidden} more paths not listed",)
    owners = _suspected_dirty_main_owners(context, [path for _status, path in shown])
    owner_lines = tuple(
        f"dirty_main_suspected_owner: {owner}" for owner in owners
    )
    if owners:
        next_action = (
            "main has uncommitted edits; ask the suspected owner to commit or "
            "revert them before rerunning this closeout: " + "; ".join(owners)
        )
    else:
        next_action = (
            "main has uncommitted edits and no active claim covers them; ask "
            "the sessions that edited main recently before rerunning this "
            "closeout"
        )
    return DirtyMainAttribution(
        file_lines=file_lines,
        owner_lines=owner_lines,
        next_action=next_action,
    )


def dirty_main_error(context: CloseoutContext) -> ManagedCloseoutError:
    """Build the dirty_main failure with attribution attached (never fails)."""

    try:
        attribution = describe_dirty_main(context)
    except (OSError, RuntimeError, ValueError):
        # Attribution is best effort: the gate must still report dirty_main
        # even when status parsing or the coordination read fails.
        return ManagedCloseoutError("dirty_main")
    error = ManagedCloseoutError("dirty_main")
    error.detail_lines = [*attribution.file_lines, *attribution.owner_lines]
    error.next_action = attribution.next_action
    return error


def _apply_dirty_main_attribution(
    result: ManagedCloseoutResult,
    error: BaseException,
) -> ManagedCloseoutResult:
    """Move a raised dirty_main error's attribution into the result envelope."""

    if getattr(error, "code", "") != "dirty_main":
        return result
    detail_lines = list(getattr(error, "detail_lines", None) or [])
    next_action = str(getattr(error, "next_action", "") or "")
    if detail_lines:
        head = result.errors[0] if result.errors else "dirty_main"
        result.errors = [head, *detail_lines]
    if next_action:
        result.next_action = next_action
    return result


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


def resolve_context(
    task_worktree: Path | str, *, base: str = "main", retain_worktree: bool = False,
) -> CloseoutContext:
    task_root = gate.repository_root(Path(task_worktree)).resolve()
    branch = gate.current_branch(task_root)
    if not branch or branch == base or not branch.startswith("codex/"):
        raise ManagedCloseoutError("invalid_task_branch")
    main_root = gate.main_worktree(task_root, base).resolve()
    if task_root == main_root or gate.current_branch(main_root) != base:
        raise ManagedCloseoutError("invalid_main_worktree")
    if gate.git_lines(main_root, "status", "--porcelain"):
        raise dirty_main_error(
            CloseoutContext(main_root=main_root, task_root=task_root, branch=branch)
        )
    if gate.git_lines(task_root, "--no-optional-locks", "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_worktree")
    expected_parent = (main_root / ".worktrees").resolve()
    context = CloseoutContext(main_root=main_root, task_root=task_root, branch=branch, base=base)
    if retain_worktree and not worktree_is_registered(context):
        raise ManagedCloseoutError("unregistered_task_worktree")
    if task_root.parent != expected_parent and not retain_worktree:
        raise ManagedCloseoutError(
            "unsafe_worktree_path",
            f"managed cleanup requires a direct child of {expected_parent}",
        )
    return context


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


def _fold_pending_declarations(context: CloseoutContext) -> str:
    """Fold declared ``.changelog`` entries into Unreleased before validation.

    The platform version watcher only settles when ``## Unreleased`` has
    content. A task that merges without rolling its declaration therefore
    leaves the version badge stuck on the previous release. Declarations stay
    on disk (``no_consume``) so a parallel task's claim is never touched; only
    ``CHANGELOG.md`` changes, and that change is committed on the task branch.
    """
    repo = context.task_root
    directory = repo / ".changelog"
    if not directory.is_dir() or not any(directory.glob("*.md")):
        return ""
    from scripts.changelog_rollup import rollup

    try:
        preview = rollup(repo, dry_run=True, no_consume=True)
    except (OSError, RuntimeError, ValueError) as error:
        return f"changelog_rollup_preview_failed: {_bounded_error(error)}"
    except SystemExit as error:
        return f"changelog_rollup_unavailable: {error}"
    if not int(preview.get("inserted") or 0):
        return ""
    try:
        rollup(repo, no_consume=True)
    except (OSError, RuntimeError, ValueError, SystemExit) as error:
        return f"changelog_rollup_failed: {_bounded_error(error)}"
    completed = gate.run_process(["git", "add", "--", "CHANGELOG.md"], repo)
    if completed.returncode != 0:
        return "changelog_rollup_add_failed: " + _bounded_error(
            completed.stderr or completed.stdout
        )
    completed = gate.run_process(
        ["git", "commit", "-m", "chore(changelog): fold pending declarations into unreleased"],
        repo,
    )
    if completed.returncode != 0:
        return "changelog_rollup_commit_failed: " + _bounded_error(
            completed.stderr or completed.stdout
        )
    return ""


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


def merge_ff_only(context: CloseoutContext, *, integration_claim_id: str, target_sha: str | None = None) -> str:
    if gate.current_branch(context.main_root) != context.base:
        raise ManagedCloseoutError("invalid_main_worktree")
    if gate.git_lines(context.main_root, "status", "--porcelain"):
        raise dirty_main_error(context)
    target_sha = gate.rev_parse(context.task_root, target_sha or "HEAD")
    old_sha = gate.rev_parse(context.main_root, "HEAD")
    hook_install.install_hooks(context.main_root)
    claim_guard.issue_main_permit(
        context.main_root,
        old_sha=old_sha,
        new_sha=target_sha,
        integration_claim_id=integration_claim_id,
    )
    try:
        completed = gate.run_process(
            ["git", "merge", "--ff-only", target_sha],
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


def _safe_main_head_sha(context: CloseoutContext) -> str:
    """Best-effort pre-merge HEAD of main; empty when Git cannot answer."""

    try:
        return gate.rev_parse(context.main_root, "HEAD")
    except Exception:  # noqa: BLE001 - the prebuild hook must never fail closeout
        return ""


def _schedule_post_merge_desktop_shell_prebuild(
    context: CloseoutContext,
    *,
    merge_sha: str,
    old_sha: str,
) -> None:
    """After a real merge advance, stage the next packaged shell in the background.

    Best-effort by contract: any failure costs one bounded stderr line and can
    never change the closeout result, and ``--cleanup-only`` (no merge) never
    reaches here. ``VIBELUTION_CLOSEOUT_DISABLE_POST_MERGE_PREBUILD=1`` disables
    the hook entirely (test isolation).
    """

    if os.environ.get("VIBELUTION_CLOSEOUT_DISABLE_POST_MERGE_PREBUILD", "").strip() == "1":
        return
    if not merge_sha or not old_sha or merge_sha == old_sha:
        return
    try:
        from core.launcher.desktop_shell import schedule_desktop_shell_prebuild

        payload = schedule_desktop_shell_prebuild(context.main_root)
        if not payload.get("scheduled"):
            print(
                f"post-merge desktop shell prebuild not scheduled: {payload.get('reason') or 'unknown'}",
                file=sys.stderr,
            )
    except Exception as error:  # noqa: BLE001 - prebuild must never fail closeout
        print(f"post-merge desktop shell prebuild failed: {str(error)[:200]}", file=sys.stderr)


def _merged_changed_paths(main_root: Path, old_sha: str, merge_sha: str) -> list[str]:
    """Return checkout-relative paths changed by ``old_sha..merge_sha``."""

    result = subprocess.run(
        ["git", "diff", "--name-only", f"{old_sha}..{merge_sha}"],
        cwd=str(main_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[:200] or "git diff failed")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _publish_post_merge_frontend_build(
    context: CloseoutContext,
    *,
    merge_sha: str,
    old_sha: str,
) -> None:
    """After a merge that touched web/, publish the release a restart will serve.

    The running backend pins the dist directory it resolved at startup, so a
    rebuilt release cannot reach an open window by itself. Publishing here only
    guarantees the next restart has the merged UI instead of the pre-merge one.
    Best-effort by contract: a failure costs one bounded stderr line.
    """

    if os.environ.get("VIBELUTION_CLOSEOUT_DISABLE_POST_MERGE_PREBUILD", "").strip() == "1":
        return
    if not merge_sha or not old_sha or merge_sha == old_sha:
        return
    try:
        changed = _merged_changed_paths(context.main_root, old_sha, merge_sha)
        if not any(path.startswith("web/") for path in changed):
            return
        from core.launcher.frontend_build import ensure_frontend_build

        payload = ensure_frontend_build(context.main_root)
        release = str(payload.get("release") or payload.get("buildKey") or "").strip()
        print(
            f"post-merge frontend published: {release or 'unknown'}; restart the workbench to serve it",
            file=sys.stderr,
        )
    except Exception as error:  # noqa: BLE001 - publishing must never fail closeout
        print(f"post-merge frontend publish failed: {str(error)[:200]}", file=sys.stderr)


# -- Post-merge version projection automation (development-standard §15) ----


def check_version_projection_consistency(
    root: Path,
    *,
    ledger_path: Path | str | None = None,
) -> list[str]:
    """Advisory VERSION projection findings; never raises, never blocks.

    The three projection files must agree with each other. When the ledger is
    readable it is compared too, but only as a warning: a settled version may
    legitimately run ahead of the files until the post-merge sync projects it.
    An unreadable ledger skips the ledger comparison entirely.
    """

    warnings: list[str] = []
    values: dict[str, str] = {}
    version_path = root / "VERSION"
    try:
        values["VERSION"] = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        warnings.append("version_projection_missing_file: VERSION")
    for name, path in (
        ("web/package.json", root / "web" / "package.json"),
        ("web/package-lock.json", root / "web" / "package-lock.json"),
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values[name] = str(payload.get("version", ""))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"version_projection_missing_file: {name}")
    distinct = {value for value in values.values() if value}
    if len(distinct) > 1:
        listed = ", ".join(f"{name}={value}" for name, value in sorted(values.items()))
        warnings.append(f"version_projection_mismatch: {listed}")
    try:
        from core.platform_version.ledger import VersionLedger

        tail = VersionLedger(root, ledger_path=ledger_path).tail()
    except (OSError, ValueError):
        return warnings
    version = values.get("VERSION", "")
    if tail is not None and version and tail.version != version:
        warnings.append(
            f"version_projection_behind_ledger: VERSION {version}, ledger tail "
            f"{tail.version} (the post-merge sync projects it; informational)"
        )
    return warnings


def _tag_exists(main_root: Path, tag: str) -> bool:
    completed = gate.run_process(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        main_root,
    )
    return completed.returncode == 0


def _create_boundary_tag(main_root: Path, boundary: dict[str, Any], sha: str) -> dict[str, Any]:
    """Create the annotated ``vX.Y.0`` tag at the sync commit (idempotent)."""

    tag = str(boundary.get("tag") or "")
    if not re.fullmatch(r"v\d+\.\d+\.0", tag) or len(sha) != 40:
        return {"ok": False, "tag": tag, "error": "invalid_boundary_payload"}
    if _tag_exists(main_root, tag):
        return {"ok": True, "tag": tag, "existed": True}
    completed = gate.run_process(
        ["git", "tag", "-a", tag, sha, "-m", tag],
        main_root,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "tag": tag,
            "error": _bounded_error(completed.stderr or completed.stdout),
        }
    return {"ok": True, "tag": tag, "existed": False}


def _create_github_release(main_root: Path, boundary: dict[str, Any], sha: str) -> dict[str, Any]:
    """Publish the release whose notes are the crossed range's CHANGELOG text."""

    tag = str(boundary.get("tag") or "")
    if shutil.which("gh") is None:
        return {"ok": False, "tag": tag, "error": "gh_cli_unavailable"}
    notes = str(boundary.get("notes") or "").strip() or tag
    handle = tempfile.NamedTemporaryFile(
        "w", suffix="-release-notes.md", encoding="utf-8", delete=False,
    )
    try:
        handle.write(notes + "\n")
        handle.close()
        completed = gate.run_process(
            [
                "gh", "release", "create", tag,
                "--title", tag,
                "--notes-file", handle.name,
                "--target", sha,
            ],
            main_root,
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    if completed.returncode != 0:
        return {
            "ok": False,
            "tag": tag,
            "error": _bounded_error(completed.stderr or completed.stdout),
        }
    return {"ok": True, "tag": tag}


def push_origin_main(main_root: Path, *, tags: Sequence[str] = ()) -> dict[str, Any]:
    """Push ``main`` (fast-forward only, never forced) plus boundary tags.

    Plain ``git push`` refuses a non-fast-forward, so a diverged remote fails
    here with the merge result untouched and authoritative.
    """

    payload: dict[str, Any] = {"ok": True, "main": {}, "tags": {}}
    completed = gate.run_process(["git", "push", "origin", "main"], main_root)
    payload["main"] = {
        "ok": completed.returncode == 0,
        "error": "" if completed.returncode == 0 else _bounded_error(completed.stderr or completed.stdout),
    }
    if not payload["main"]["ok"]:
        payload["ok"] = False
    for tag in tags:
        completed = gate.run_process(["git", "push", "origin", f"refs/tags/{tag}"], main_root)
        payload["tags"][tag] = {
            "ok": completed.returncode == 0,
            "error": "" if completed.returncode == 0 else _bounded_error(completed.stderr or completed.stdout),
        }
        if not payload["tags"][tag]["ok"]:
            payload["ok"] = False
    return payload


def publish_version_projection(
    context: CloseoutContext,
    *,
    integration_claim_id: str,
    push_remote: bool = True,
    ledger_path: Path | str | None = None,
) -> dict[str, Any]:
    """Settle + project the version on ``main``, then publish it.

    Never raises: every failure is recorded in the payload, because the merge
    that already happened stays authoritative regardless of what publishing
    does. The sync commit is created under the still-live integration lease
    (the main-update permit requires it); tag, release and push only run when
    ``push_remote`` is set (the ``--no-push`` offline escape).
    """

    payload: dict[str, Any] = {
        "ok": False,
        "sync": {},
        "tag": {},
        "release": {},
        "push": {},
        "errors": [],
    }
    try:
        from scripts.sync_platform_version_projections import sync_version_projections

        payload["sync"] = sync_version_projections(
            context.main_root,
            ledger_path=ledger_path,
            integration_claim_id=integration_claim_id,
        )
    except Exception as error:  # noqa: BLE001 - publish must never fail the merge
        payload["sync"] = {"ok": False, "errors": [_bounded_error(error)]}
    if not payload["sync"].get("ok"):
        payload["errors"].append("version_sync_failed")
        return payload
    if not push_remote:
        payload["push"] = {"ok": True, "skipped": True}
        payload["ok"] = True
        return payload
    boundary = payload["sync"].get("boundary")
    sync_sha = str(payload["sync"].get("commitSha") or "")
    tags: list[str] = []
    if boundary:
        tag_result = _create_boundary_tag(context.main_root, boundary, sync_sha)
        payload["tag"] = tag_result
        if tag_result.get("ok"):
            tags = [str(tag_result["tag"])]
        else:
            payload["errors"].append("boundary_tag_failed")
    push = push_origin_main(context.main_root, tags=tags)
    payload["push"] = push
    if not push.get("ok"):
        payload["errors"].append("push_failed")
    if boundary and tags and payload["push"].get("main", {}).get("ok"):
        release = _create_github_release(context.main_root, boundary, sync_sha)
        payload["release"] = release
        if not release.get("ok"):
            payload["errors"].append("release_failed")
    payload["ok"] = not payload["errors"]
    return payload


def _publish_summaries(publish_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one publish payload into the ``versionSync`` and ``push`` result fields."""

    if not publish_payload:
        return {}, {}
    sync = dict(publish_payload.get("sync") or {})
    summary = {
        "ok": bool(publish_payload.get("ok")),
        "newVersion": str(sync.get("newVersion") or ""),
        "commitSha": str(sync.get("commitSha") or ""),
        "boundary": sync.get("boundary"),
        "tag": publish_payload.get("tag") or {},
        "release": publish_payload.get("release") or {},
        "errors": list(publish_payload.get("errors") or []),
    }
    return summary, dict(publish_payload.get("push") or {})


def _skipped_publish_summaries(reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Explicit ``versionSync``/``push`` markers for a run where publish did not execute.

    A merged result that stays pending must never leave the publish outcome
    silent: an empty ``versionSync`` cannot be told apart from a lost one, so
    every skip names its reason and the debt stays recoverable with
    ``--cleanup-only --publish``.
    """

    marker = {"ok": False, "skipped_reason": reason}
    return dict(marker), dict(marker)


def _publish_debt_outstanding(version_sync: dict[str, Any] | None) -> bool:
    """Whether a closeout result carries an unfinished version-publish debt.

    True for a failed or not-attempted publish (the debt needs a
    ``--cleanup-only --publish`` rerun); false for a settled publish, a
    deliberate ``publish_not_requested`` skip, or legacy empty fields.
    """

    if not version_sync:
        return False
    if version_sync.get("skipped_reason") == "publish_not_requested":
        return False
    return not version_sync.get("ok", False)


def _publish_pending_result(
    publish_payload: dict[str, Any],
    *,
    next_action: str,
    warnings: list[str] | None = None,
) -> ManagedCloseoutResult:
    sync_summary, push_summary = _publish_summaries(publish_payload)
    return ManagedCloseoutResult(
        status="merged_publish_pending",
        exit_code=MERGED_PUBLISH_PENDING_EXIT_CODE,
        merged=True,
        retryable=True,
        next_action=next_action,
        errors=[f"version_publish_pending: {error}" for error in sync_summary.get("errors", [])],
        warnings=warnings or [],
        versionSync=sync_summary,
        push=push_summary,
    )


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


def registered_worktree_roots(context: CloseoutContext) -> set[str]:
    """Resolved, case-normalized paths of the worktrees Git currently tracks."""

    completed = gate.run_process(["git", "worktree", "list", "--porcelain"], context.main_root)
    if completed.returncode != 0:
        raise ManagedCloseoutError("worktree_list_failed", _bounded_error(completed.stderr))
    roots: set[str] = set()
    for line in completed.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        raw = line.removeprefix("worktree ").strip()
        if raw:
            roots.add(os.path.normcase(str(Path(raw).resolve())))
    return roots


def worktree_is_registered(context: CloseoutContext) -> bool:
    """Whether this checkout is still a registered worktree of the main repo.

    Git commands run with ``cwd`` inside an *unregistered* leftover directory
    resolve to the main repository instead, so every check that reads task state
    through Git has to be gated on this rather than on ``is_dir()``.
    """

    if not context.task_root.is_dir():
        return False
    return os.path.normcase(str(context.task_root.resolve())) in registered_worktree_roots(context)


def _remove_leftover_worktree_dir(context: CloseoutContext) -> None:
    """Finish a half-completed worktree removal by deleting the residue.

    ``git worktree remove`` unregisters the worktree and deletes its contents,
    then may fail to delete the directory itself (a Windows lock on the path,
    typically a process whose working directory is inside it). Retrying the Git
    command then reports "is not a working tree" even though only an empty
    directory is left.

    Only an empty directory is removed here.  Any remaining entry is reported
    instead, because a half-deleted checkout can still hold untracked content
    whose ownership this script cannot judge.
    """

    deadline = time.monotonic() + CLEANUP_RETRY_SECONDS
    while True:
        if not context.task_root.is_dir():
            return
        unreadable = False
        try:
            residue = sorted(entry.name for entry in context.task_root.iterdir())
        except OSError:
            residue = []
            unreadable = True
        if not unreadable and not residue:
            try:
                context.task_root.rmdir()
            except FileNotFoundError:
                return
            except OSError:
                pass
            else:
                return
        if time.monotonic() >= deadline:
            if unreadable:
                detail = "not readable"
            elif residue:
                detail = ", ".join(residue)
            else:
                detail = "empty directory is still locked"
            raise ManagedCloseoutError(
                "cleanup_residue_present",
                f"{context.task_root}: {detail}",
            )
        time.sleep(CLEANUP_RETRY_DELAY_SECONDS)


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
    # Task state must be read through Git only while this directory is still a
    # registered worktree; otherwise those commands silently answer for the main
    # repository (its status, its HEAD) and the checks below stop meaning what
    # they say.
    worktree_registered = worktree_is_registered(context)
    if worktree_registered and gate.git_lines(context.task_root, "status", "--porcelain"):
        raise ManagedCloseoutError("dirty_worktree")
    branch_exists = _branch_exists(context)
    task_head = (
        gate.rev_parse(context.task_root, "HEAD")
        if worktree_registered
        else gate.rev_parse(context.main_root, context.branch) if branch_exists else ""
    )
    main_head = gate.rev_parse(context.main_root, "HEAD")
    if task_head and not gate.is_ancestor(context.main_root, task_head, main_head):
        raise ManagedCloseoutError("branch_not_merged")
    expected_parent = (context.main_root / ".worktrees").resolve()
    if context.task_root.resolve().parent != expected_parent:
        raise ManagedCloseoutError("unsafe_worktree_path")

    if task_exists:
        if worktree_registered:
            for relative in TASK_OWNED_EPHEMERAL_PATHS:
                _remove_link_or_junction(context.task_root / relative)
            if invocation_cwd_is_inside_task(context.task_root):
                os.chdir(context.main_root)
            removed = _remove_worktree_with_retry(context)
            if removed.returncode != 0 and worktree_is_registered(context):
                raise ManagedCloseoutError(
                    "worktree_remove_failed",
                    _bounded_error(removed.stderr or removed.stdout),
                )
        _remove_leftover_worktree_dir(context)
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
    # Targeted removal already unregisters this task. A repository-wide prune
    # could discard recovery metadata for another task's unavailable checkout.


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
        raise dirty_main_error(
            CloseoutContext(main_root=main_root, task_root=task_root, branch=branch)
        )
    if not branch.startswith("codex/") or branch == "codex/":
        raise ManagedCloseoutError("invalid_task_branch")
    if task_root.is_dir():
        resolved_root = gate.repository_root(task_root).resolve()
        if resolved_root == task_root:
            if gate.current_branch(task_root) != branch:
                raise ManagedCloseoutError("invalid_task_branch")
        elif resolved_root != main_root:
            raise ManagedCloseoutError("unsafe_worktree_path")
        # Otherwise the directory is residue from a half-completed removal: Git
        # resolves it to the main repository, and cleanup finishes deleting it
        # instead of refusing the recovery the caller was told to run.
    return CloseoutContext(main_root=main_root, task_root=task_root, branch=branch)


def run_cleanup_only(
    task_worktree: Path | str,
    *,
    branch: str,
    agent_id: str,
    base: str = "main",
    publish: bool = False,
    push_remote: bool = True,
) -> ManagedCloseoutResult:
    publish_payload: dict[str, Any] = {}
    try:
        context = resolve_cleanup_context(task_worktree, branch=branch, base=base)
        cleanup_task_resources(context, agent_id=agent_id)
        prune_coordination(context)
        if publish:
            claim_id = acquire_integration_claim_with_retry(
                context,
                agent_id=agent_id,
            )
            try:
                publish_payload = publish_version_projection(
                    context,
                    integration_claim_id=claim_id,
                    push_remote=push_remote,
                )
            finally:
                release_claim(
                    context,
                    claim_id,
                    status="completed" if publish_payload.get("ok") else "released",
                    reason="version publish lease finished",
                )
    except (OSError, RuntimeError, ValueError) as error:
        if publish:
            # Cleanup failed before publish could run, so the publish debt is
            # still open: name the rerun that finishes cleanup and publish
            # together instead of pointing at a plain cleanup-only recovery.
            publish_summary, push_summary = _skipped_publish_summaries("publish_not_attempted")
            next_action = "rerun_cleanup_only_with_publish_from_main"
        else:
            publish_summary, push_summary = _skipped_publish_summaries("publish_not_requested")
            next_action = "rerun_cleanup_only_from_main"
        return _apply_dirty_main_attribution(
            ManagedCloseoutResult(
                status="merged_cleanup_pending",
                exit_code=2,
                merged=True,
                retryable=True,
                next_action=next_action,
                errors=[_bounded_error(error)],
                versionSync=publish_summary,
                push=push_summary,
            ),
            error,
        )
    if publish_payload and not publish_payload.get("ok", True):
        return _publish_pending_result(
            publish_payload,
            next_action="rerun_cleanup_only_with_publish_from_main",
        )
    sync_summary, push_summary = _publish_summaries(publish_payload)
    return ManagedCloseoutResult(
        status="merged_clean",
        exit_code=0,
        merged=True,
        versionSync=sync_summary,
        push=push_summary,
    )


def _manifest_field(manifest_path: Path | str | None, field: str) -> Any:
    """Best-effort read of one manifest field for stale-main classification."""

    if manifest_path is None:
        return None
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload.get(field)


def classify_stale_main_recovery(
    context: CloseoutContext,
    *,
    base: str,
    manifest_path: Path | str | None = None,
) -> tuple[str, str]:
    """Name the one mechanical next step behind a ``stale_main`` outcome.

    ``stale_main`` covers three different situations. Naming the right one keeps
    the caller from guessing, and avoids handing back a one-use retry token that
    the caller's own recovery step would invalidate:

    - the task branch does not contain current ``main`` yet -> merge ``main`` in;
    - ``main`` advanced over paths this task validated -> re-run validation;
    - ``main`` advanced elsewhere only -> reuse the manifest under a token.
    """

    try:
        task_head = gate.rev_parse(context.task_root, "HEAD")
        current_main = gate.main_revision_sha(context.task_root, base)
    except (OSError, RuntimeError, ValueError) as error:
        return "rerun_validation", _bounded_error(error)
    if not gate.is_ancestor(context.task_root, current_main, task_head):
        return (
            "merge_main_into_task_branch",
            f"task branch does not contain {base} at {current_main[:12]}",
        )
    validated_main_sha = str(_manifest_field(manifest_path, "validatedMainSha") or "")
    files = [
        item
        for item in (_manifest_field(manifest_path, "changedFiles") or [])
        if isinstance(item, str)
    ]
    if (
        validated_main_sha
        and files
        and gate.main_advance_skips_files(
            context.task_root,
            base,
            validated_main_sha,
            files,
        )
    ):
        return "sync_main_then_reserve_with_token", ""
    return "rerun_validation", f"{base} advanced over paths this task validated"


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
    retain_worktree: bool = False,
    publish: bool = False,
    push_remote: bool = True,
) -> ManagedCloseoutResult:
    changelog_fold_warning = ""
    try:
        context = resolve_context(task_worktree, base=base, retain_worktree=retain_worktree)
        claim_id, agent_id = resolve_claim_identity(
            context,
            claim_id=claim_id,
            agent_id=agent_id,
        )
        from scripts import git_history_closeout

        history_result = git_history_closeout.run_if_needed(
            context, claim_id=claim_id, agent_id=agent_id, base=base,
            integration_wait_seconds=integration_wait_seconds,
        )
        if history_result is not None:
            return history_result
        validate_development_claim(context, claim_id=claim_id, agent_id=agent_id)
        changelog_fold_warning = _fold_pending_declarations(context)
    except (OSError, RuntimeError, ValueError) as error:
        code = getattr(error, "code", "")
        expired_claim = code == "invalid_development_claim"
        return _apply_dirty_main_attribution(
            ManagedCloseoutResult(
                status="failed",
                exit_code=1,
                retryable=expired_claim,
                next_action="refresh_development_claim" if expired_claim else "",
                errors=[_bounded_error(error)],
            ),
            error,
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
                # ``detail`` carries the one actionable sentence behind link
                # preflight outcomes (which tree is missing, why creation
                # failed); every other outcome leaves it empty, so the exact
                # ``errors == [...]`` stale_main/head_moved checks below hold.
                validation_result = ManagedCloseoutResult(
                    status="validation_failed",
                    exit_code=1,
                    manifest_path=manifest_path_text,
                    errors=[
                        str(closeout.outcome),
                        *([closeout.detail] if closeout.detail else []),
                    ],
                    failures=command_failure_details(closeout.outcome, closeout.commands),
                )

        if validation_result is None and not manifest_preverified:
            verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
            if verified.outcome != "passed":
                validation_result = ManagedCloseoutResult(
                    status="validation_failed",
                    exit_code=1,
                    manifest_path=manifest_path_text,
                    errors=[str(verified.outcome)],
                    failures=command_failure_details(verified.outcome, verified.commands),
                )
    except (OSError, RuntimeError, ValueError) as error:
        validation_result = ManagedCloseoutResult(
            status="failed",
            exit_code=1,
            manifest_path=manifest_path_text,
            errors=[_bounded_error(error)],
        )

    # Advisory projection consistency: recorded on the result but never
    # blocking. The ledger comparison is informational only — a settled
    # version legitimately runs ahead of the files until the post-merge sync.
    consistency_warnings = check_version_projection_consistency(
        context.task_root,
        ledger_path=resolve_ledger_path(context.main_root),
    )

    if validation_result is not None:
        if (
            validation_result.errors == ["stale_main"]
            and resolved_manifest is not None
        ):
            stale_action, stale_detail = classify_stale_main_recovery(
                context,
                base=base,
                manifest_path=resolved_manifest,
            )
            validation_result.retryable = True
            validation_result.next_action = stale_action
            if stale_detail:
                validation_result.errors.append(stale_detail)
            if stale_action == "sync_main_then_reserve_with_token":
                try:
                    retry_token = issue_stale_retry_token(
                        resolved_manifest,
                        context,
                        agent_id=agent_id,
                    )
                    validation_result.retry_token_path = str(retry_token)
                except OSError as error:
                    validation_result.errors.append(
                        f"stale_retry_token_pending: {_bounded_error(error)}"
                    )
        if validation_result.errors == ["head_moved"]:
            # The validated task content changed after the run. Nothing in the
            # manifest can be reused, so the only correct next step is a fresh
            # validation of the current head; no token is issued for that.
            validation_result.retryable = True
            validation_result.next_action = "rerun_closeout_for_current_head"
        recoverable_action = RECOVERABLE_VALIDATION_ACTIONS.get(
            validation_result.errors[0] if validation_result.errors else ""
        )
        if recoverable_action:
            # Mechanically recoverable: apply the named step, then re-run the same
            # closeout. No rebase and no token are needed because the tree did not
            # change; this check runs before the expensive commands.
            validation_result.retryable = True
            validation_result.next_action = recoverable_action
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
    publish_payload: dict[str, Any] = {}
    result = ManagedCloseoutResult(status="failed", exit_code=1)
    try:
        verified = gate.verify_manifest(resolved_manifest, context.task_root, base)
        if verified.outcome != "passed":
            retry_token_path = ""
            retryable = False
            next_action = ""
            if verified.outcome == "stale_main":
                next_action, _stale_detail = classify_stale_main_recovery(
                    context,
                    base=base,
                    manifest_path=resolved_manifest,
                )
                retryable = True
                if next_action == "sync_main_then_reserve_with_token":
                    retry_token = issue_stale_retry_token(
                        resolved_manifest,
                        context,
                        agent_id=agent_id,
                    )
                    retry_token_path = str(retry_token)
            elif verified.outcome == "head_moved":
                retryable = True
                next_action = "rerun_closeout_for_current_head"
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
            pre_merge_sha = _safe_main_head_sha(context)
            merge_sha = merge_ff_only(
                context,
                integration_claim_id=integration_claim_id,
            )
            # Version sync runs while the integration lease is still live: the
            # sync commit moves main through a claim-bound permit. Its outcome
            # (and the push outcome) is recorded on the result and can never
            # invalidate the merge above.
            publish_payload: dict[str, Any] = {}
            if publish:
                publish_payload = publish_version_projection(
                    context,
                    integration_claim_id=integration_claim_id,
                    push_remote=push_remote,
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
            _schedule_post_merge_desktop_shell_prebuild(
                context,
                merge_sha=merge_sha,
                old_sha=pre_merge_sha,
            )
            _publish_post_merge_frontend_build(
                context,
                merge_sha=merge_sha,
                old_sha=pre_merge_sha,
            )
            cleanup_errors: list[str] = []
            if not retain_worktree:
                try:
                    cleanup_task_resources(context, agent_id=agent_id)
                except (OSError, RuntimeError, ValueError) as error:
                    cleanup_errors.append(_bounded_error(error))
            try:
                complete_agent(context, agent_id=agent_id, merge_sha=merge_sha)
                prune_coordination(context)
            except (OSError, RuntimeError, ValueError) as error:
                cleanup_errors.append(_bounded_error(error))
            cleanup_pending = bool(cleanup_errors or retain_worktree)
            if publish_payload:
                sync_field = publish_payload.get("sync", {})
                push_field = publish_payload.get("push", {})
            elif cleanup_pending:
                # A pending merged result must never leave the publish outcome
                # silent: name why publish did not produce fields.
                sync_field, push_field = _skipped_publish_summaries(
                    "publish_not_attempted" if publish else "publish_not_requested"
                )
            else:
                sync_field, push_field = {}, {}
            result = ManagedCloseoutResult(
                status="merged_cleanup_pending" if cleanup_pending else "merged_clean",
                exit_code=2 if cleanup_errors else 0,
                merged=True,
                merge_sha=merge_sha,
                manifest_path=manifest_path_text,
                retryable=bool(cleanup_errors),
                next_action=(
                    "retain_worktree_until_owner_releases_it" if retain_worktree
                    else "run_cleanup_only_from_main" if cleanup_errors else ""
                ),
                errors=cleanup_errors,
                warnings=(
                    [*consistency_warnings, changelog_fold_warning]
                    if changelog_fold_warning
                    else consistency_warnings
                ),
                versionSync=sync_field,
                push=push_field,
            )
            if publish and not publish_payload:
                # Defensive: publish was requested but produced no payload
                # (publish_version_projection normally never raises). Keep the
                # debt explicit so the recovery rerun finishes it.
                result.errors.append("version_publish_pending: publish_not_attempted")
                if cleanup_errors:
                    result.next_action = "rerun_cleanup_only_with_publish_from_main"
            elif publish_payload and not publish_payload.get("ok", True):
                publish_summary, push_summary = _publish_summaries(publish_payload)
                result.versionSync = publish_summary
                result.push = push_summary
                if cleanup_errors or retain_worktree:
                    # Cleanup recovery stays the primary next action; the
                    # publish debt is recorded alongside it and is finished by
                    # rerunning cleanup-only with --publish.
                    result.errors.append(
                        "version_publish_pending: " + ", ".join(publish_summary.get("errors", []))
                    )
                    if cleanup_errors:
                        # One rerun from main finishes both debts, so the
                        # recovery step must ask for --publish explicitly.
                        result.next_action = "rerun_cleanup_only_with_publish_from_main"
                else:
                    result.status = "merged_publish_pending"
                    result.exit_code = MERGED_PUBLISH_PENDING_EXIT_CODE
                    result.retryable = True
                    result.next_action = "rerun_cleanup_only_with_publish_from_main"
                    result.errors = [
                        f"version_publish_pending: {error}"
                        for error in publish_summary.get("errors", [])
                    ]
    except (OSError, RuntimeError, ValueError) as error:
        if merge_sha:
            status: CloseoutStatus = "merged_cleanup_pending"
            exit_code = 2
        else:
            status = "failed"
            exit_code = 1
        errors = [_bounded_error(error)]
        if not publish_payload and merge_sha:
            if publish:
                # The merge is authoritative, but publish never ran: the debt
                # must stay explicit so a cleanup-only --publish rerun can
                # finish it instead of the loss staying invisible.
                publish_summary, push_summary = _skipped_publish_summaries("publish_not_attempted")
                errors.append("version_publish_pending: publish_not_attempted")
                next_action = "rerun_cleanup_only_with_publish_from_main"
            else:
                publish_summary, push_summary = _skipped_publish_summaries("publish_not_requested")
                next_action = "run_cleanup_only_from_main"
        else:
            publish_summary, push_summary = _publish_summaries(publish_payload)
            next_action = "run_cleanup_only_from_main" if merge_sha else ""
        result = _apply_dirty_main_attribution(
            ManagedCloseoutResult(
                status=status,
                exit_code=exit_code,
                merged=bool(merge_sha),
                merge_sha=merge_sha,
                manifest_path=manifest_path_text,
                retryable=bool(merge_sha),
                next_action=next_action,
                errors=errors,
                warnings=(
                    [*consistency_warnings, changelog_fold_warning]
                    if changelog_fold_warning
                    else consistency_warnings
                ),
                versionSync=publish_summary,
                push=push_summary,
            ),
            error,
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
                    # Do not overwrite an outstanding publish debt with a
                    # plain-cleanup recovery step.
                    result.next_action = (
                        "rerun_cleanup_only_with_publish_from_main"
                        if _publish_debt_outstanding(result.versionSync)
                        else "run_cleanup_only_from_main"
                    )
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
    cleanup_mode = parser.add_mutually_exclusive_group()
    cleanup_mode.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Resume safe local cleanup after a merge already succeeded.",
    )
    cleanup_mode.add_argument(
        "--retain-worktree",
        action="store_true",
        help="Validate and merge a registered worktree without deleting it, its branch, or its dependency links.",
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
    parser.add_argument(
        "--publish",
        action="store_true",
        help=(
            "With --cleanup-only: after cleanup, also settle/project the version "
            "on main and push it (tag + release on cadence boundaries)."
        ),
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip the post-merge version sync chain entirely (no sync, tag, release or push).",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help=(
            "Run the version sync locally but skip every network step "
            "(tag push, gh release, git push) for offline recovery."
        ),
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
                publish=args.publish,
                push_remote=not args.no_push,
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
            retain_worktree=args.retain_worktree,
            publish=not args.no_publish,
            push_remote=not args.no_push,
        )
    print(json.dumps(asdict(result), ensure_ascii=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
