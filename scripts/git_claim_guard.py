from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

PERMIT_SCHEMA_VERSION = 1
PERMIT_TTL_SECONDS = 60
ACTIVE_CLAIM_STATUSES = {"active", "ready"}


class ClaimGuardError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimBinding:
    claim_id: str
    agent_id: str
    branch: str
    worktree: str
    scopes: tuple[str, ...]


def _run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_value(root: Path, *arguments: str) -> str:
    completed = _run_git(root, *arguments)
    if completed.returncode != 0:
        raise ClaimGuardError(completed.stderr.strip() or "git_command_failed")
    return completed.stdout.strip()


def repository_root(root: Path | str) -> Path:
    return Path(_git_value(Path(root), "rev-parse", "--show-toplevel")).resolve()


def _git_path(root: Path, option: str) -> Path:
    value = Path(_git_value(root, "rev-parse", "--path-format=absolute", option))
    return value.resolve()


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").strip("/").lower() or "."


def _scope_covers(scope: str, path: str) -> bool:
    scope_value = _normalize_path(scope)
    path_value = _normalize_path(path)
    if scope_value in {"*", ".", "repo", "repository", "project", "project-root"}:
        return True
    return path_value == scope_value or path_value.startswith(f"{scope_value}/")


def _claim_covers(claim: dict[str, object], paths: Sequence[str]) -> bool:
    scopes = claim.get("scopes")
    return isinstance(scopes, list) and all(
        any(isinstance(scope, str) and _scope_covers(scope, path) for scope in scopes)
        for path in paths
    )


def _binding_path(root: Path) -> Path:
    return _git_path(root, "--git-dir") / "vibelution-claim.json"


def _permit_path(root: Path) -> Path:
    return (
        _git_path(root, "--git-common-dir")
        / "vibelution-cache"
        / "main-ref-permit.json"
    )


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_claim_binding(root: Path | str) -> ClaimBinding | None:
    root_path = repository_root(root)
    path = _binding_path(root_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scopes = payload["scopes"]
        if not isinstance(scopes, list) or not all(
            isinstance(item, str) for item in scopes
        ):
            return None
        return ClaimBinding(
            claim_id=str(payload["claim_id"]),
            agent_id=str(payload["agent_id"]),
            branch=str(payload["branch"]),
            worktree=str(payload["worktree"]),
            scopes=tuple(scopes),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_claim_binding(root: Path, binding: ClaimBinding) -> None:
    _write_json_atomic(_binding_path(root), asdict(binding))


def _coordination_script() -> Path:
    candidates = (
        Path.home()
        / ".codex"
        / "skills"
        / "briefbound-project-memory"
        / "scripts"
        / "agent_coordination.py",
        Path.home()
        / ".codex"
        / "skills"
        / "ccdawn-dawn-agent-html-memory"
        / "scripts"
        / "agent_work_guard.py",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ClaimGuardError("coordination_unavailable")


def coordination_call(root: Path, *arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(_coordination_script()), str(root), *arguments, "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ClaimGuardError(
            "claim_overlap" if "conflict" in detail.lower() else "coordination_failed"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ClaimGuardError("coordination_invalid_response") from error
    if not isinstance(payload, dict):
        raise ClaimGuardError("coordination_invalid_response")
    return payload


def staged_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ClaimGuardError("staged_paths_unavailable")
    return tuple(
        sorted(
            {
                item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                for item in completed.stdout.split(b"\0")
                if item
            }
        )
    )


def committed_task_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "-z", "main...HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ClaimGuardError("task_paths_unavailable")
    return tuple(
        sorted(
            {
                item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                for item in completed.stdout.split(b"\0")
                if item
            }
        )
    )


def _same_worktree(value: object, root: Path) -> bool:
    if not value:
        return False
    try:
        return os.path.normcase(str(Path(str(value)).resolve())) == os.path.normcase(
            str(root.resolve())
        )
    except OSError:
        return False


def _auto_agent_id(root: Path, branch: str) -> str:
    identity = f"{_git_path(root, '--git-common-dir')}\0{root.resolve()}\0{branch}"
    return f"worktree-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def ensure_development_claim(root: Path | str) -> ClaimBinding | None:
    root_path = repository_root(root)
    branch = _git_value(root_path, "branch", "--show-current")
    if not branch.startswith("codex/"):
        raise ClaimGuardError("task_branch_required")
    staged = staged_paths(root_path)
    if not staged:
        return None
    paths = tuple(sorted(set(staged) | set(committed_task_paths(root_path))))

    status = coordination_call(root_path, "status")
    agents = status.get("agents") if isinstance(status.get("agents"), list) else []
    claims = status.get("claims") if isinstance(status.get("claims"), list) else []
    matching_agents = [
        item
        for item in agents
        if isinstance(item, dict)
        and item.get("state") in {"active", "paused"}
        and item.get("branch") == branch
        and _same_worktree(item.get("worktree"), root_path)
    ]
    if len(matching_agents) > 1:
        raise ClaimGuardError("ambiguous_worktree_owner")

    agent_id = (
        str(matching_agents[0].get("id"))
        if matching_agents
        else _auto_agent_id(root_path, branch)
    )
    covering = [
        item
        for item in claims
        if isinstance(item, dict)
        and item.get("agentId") == agent_id
        and item.get("status") in ACTIVE_CLAIM_STATUSES
        and _claim_covers(item, paths)
    ]
    if len(covering) > 1:
        raise ClaimGuardError("ambiguous_covering_claim")

    if covering:
        claim = covering[0]
    else:
        if not matching_agents:
            coordination_call(
                root_path,
                "join",
                "--agent",
                f"Worktree {branch}",
                "--agent-id",
                agent_id,
                "--task",
                f"Develop {branch}",
                "--state",
                "active",
                "--stage",
                "development",
                "--branch",
                branch,
                "--worktree",
                str(root_path),
                *(value for path in paths for value in ("--scope", path)),
                "--ttl-minutes",
                "240",
            )
        for existing in claims:
            if (
                isinstance(existing, dict)
                and existing.get("agentId") == agent_id
                and existing.get("status") in ACTIVE_CLAIM_STATUSES
                and isinstance(existing.get("id"), str)
                and any(
                    _scope_covers(str(scope), path) or _scope_covers(path, str(scope))
                    for scope in existing.get("scopes", [])
                    if isinstance(scope, str)
                    for path in paths
                )
            ):
                coordination_call(
                    root_path,
                    "release",
                    "--claim-id",
                    str(existing["id"]),
                    "--status",
                    "released",
                    "--reason",
                    "Replaced by an automatic aggregate claim for the current task diff",
                )
        payload = coordination_call(
            root_path,
            "claim",
            "--lane",
            f"development/{branch.removeprefix('codex/')}",
            *(value for path in paths for value in ("--scope", path)),
            "--agent-id",
            agent_id,
            "--task",
            f"Develop {branch}",
            "--status",
            "active",
            "--ttl-minutes",
            "240",
            "--note",
            "Automatically claimed staged paths by the pre-commit guard",
        )
        claim = payload.get("claim")
        if not isinstance(claim, dict) or not claim.get("id"):
            raise ClaimGuardError("claim_not_created")

    scopes = claim.get("scopes")
    binding = ClaimBinding(
        claim_id=str(claim["id"]),
        agent_id=agent_id,
        branch=branch,
        worktree=str(root_path),
        scopes=tuple(str(item) for item in scopes)
        if isinstance(scopes, list)
        else paths,
    )
    _write_claim_binding(root_path, binding)
    return binding


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def issue_main_permit(
    root: Path | str,
    *,
    old_sha: str,
    new_sha: str,
    integration_claim_id: str,
    now: datetime | None = None,
) -> Path:
    if not integration_claim_id or len(old_sha) != 40 or len(new_sha) != 40:
        raise ClaimGuardError("invalid_main_update_permit")
    issued_at = now or _utc_now()
    path = _permit_path(repository_root(root))
    _write_json_atomic(
        path,
        {
            "schemaVersion": PERMIT_SCHEMA_VERSION,
            "oldSha": old_sha,
            "newSha": new_sha,
            "integrationClaimId": integration_claim_id,
            "issuedAt": issued_at.isoformat().replace("+00:00", "Z"),
            "expiresAt": (issued_at + timedelta(seconds=PERMIT_TTL_SECONDS))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )
    return path


def clear_main_permit(root: Path | str) -> None:
    path = _permit_path(repository_root(root))
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _main_update(lines: TextIO) -> tuple[str, str] | None:
    updates = []
    for raw in lines:
        parts = raw.strip().split()
        if len(parts) == 3 and parts[2] == "refs/heads/main":
            updates.append((parts[0], parts[1]))
    if len(updates) > 1:
        raise ClaimGuardError("ambiguous_main_update")
    return updates[0] if updates else None


def _read_permit(root: Path) -> dict[str, object]:
    try:
        payload = json.loads(_permit_path(root).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ClaimGuardError("main_update_permit_required") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ClaimGuardError("main_update_permit_invalid") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != PERMIT_SCHEMA_VERSION
    ):
        raise ClaimGuardError("main_update_permit_invalid")
    return payload


def check_reference_transaction(
    root: Path | str,
    phase: str,
    lines: TextIO,
    *,
    now: datetime | None = None,
) -> None:
    root_path = repository_root(root)
    update = _main_update(lines)
    if update is None:
        return
    payload = _read_permit(root_path)
    if update != (payload.get("oldSha"), payload.get("newSha")):
        raise ClaimGuardError("main_update_permit_mismatch")
    if phase in {"preparing", "prepared"}:
        try:
            expires_at = datetime.fromisoformat(
                str(payload["expiresAt"]).replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as error:
            raise ClaimGuardError("main_update_permit_invalid") from error
        if (now or _utc_now()) > expires_at:
            raise ClaimGuardError("main_update_permit_expired")
    elif phase in {"committed", "aborted"}:
        clear_main_permit(root_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guard Vibelution development claims and main ref updates."
    )
    parser.add_argument("command", choices=["ensure-claim", "reference-transaction"])
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--phase", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ensure-claim":
            binding = ensure_development_claim(args.repo)
            if binding is not None:
                print(json.dumps(asdict(binding), ensure_ascii=True))
        else:
            if not args.phase:
                raise ClaimGuardError("reference_transaction_phase_required")
            check_reference_transaction(args.repo, args.phase, sys.stdin)
    except ClaimGuardError as error:
        print(f"[claim-guard] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
