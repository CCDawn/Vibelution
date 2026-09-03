from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import git_claim_guard as guard
from scripts import local_quality_gate as gate
from scripts import task_closeout as closeout


def _git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Claim Guard Test")
    _git(root, "config", "user.email", "claim-guard@test.local")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")
    return root


def test_ensure_claim_automatically_claims_staged_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _git(root, "switch", "-c", "codex/example")
    (root / "scripts").mkdir()
    (root / "scripts" / "one.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", "scripts/one.py")
    calls: list[tuple[str, ...]] = []

    def coordination(_root: Path, *arguments: str) -> dict[str, object]:
        calls.append(arguments)
        if arguments[0] == "status":
            return {"agents": [], "claims": []}
        if arguments[0] == "join":
            return {"id": arguments[arguments.index("--agent-id") + 1]}
        assert arguments[0] == "claim"
        return {
            "ok": True,
            "claim": {
                "id": "claim-auto",
                "agentId": arguments[arguments.index("--agent-id") + 1],
                "scopes": ["scripts/one.py"],
            },
        }

    monkeypatch.setattr(guard, "coordination_call", coordination)

    binding = guard.ensure_development_claim(root)

    assert binding.claim_id == "claim-auto"
    claim_call = next(item for item in calls if item[0] == "claim")
    assert claim_call[claim_call.index("--scope") + 1] == "scripts/one.py"
    assert guard.read_claim_binding(root) == binding


def test_ensure_claim_rejects_real_scope_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _git(root, "switch", "-c", "codex/example")
    (root / "hot.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", "hot.py")

    monkeypatch.setattr(
        guard,
        "coordination_call",
        lambda _root, *args: (
            {"agents": [], "claims": []}
            if args[0] == "status"
            else {"id": args[args.index("--agent-id") + 1]}
            if args[0] == "join"
            else (_ for _ in ()).throw(guard.ClaimGuardError("claim_overlap"))
        ),
    )

    with pytest.raises(guard.ClaimGuardError, match="claim_overlap"):
        guard.ensure_development_claim(root)

    assert guard.read_claim_binding(root) is None


def test_existing_worktree_owner_and_covering_claim_are_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _git(root, "switch", "-c", "codex/example")
    (root / "owned.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", "owned.py")
    root_text = os.path.normcase(str(root.resolve()))

    def coordination(_root: Path, *arguments: str) -> dict[str, object]:
        assert arguments == ("status",)
        return {
            "agents": [
                {
                    "id": "agent-existing",
                    "state": "active",
                    "branch": "codex/example",
                    "worktree": root_text,
                }
            ],
            "claims": [
                {
                    "id": "claim-existing",
                    "agentId": "agent-existing",
                    "status": "active",
                    "scopes": ["owned.py"],
                }
            ],
        }

    monkeypatch.setattr(guard, "coordination_call", coordination)
    binding = guard.ensure_development_claim(root)
    assert binding.claim_id == "claim-existing"
    assert binding.agent_id == "agent-existing"


def test_later_commit_replaces_own_partial_claim_with_task_diff_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    _git(root, "switch", "-c", "codex/example")
    (root / "first.py").write_text("first = 1\n", encoding="utf-8")
    _git(root, "add", "first.py")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "first")
    (root / "second.py").write_text("second = 1\n", encoding="utf-8")
    _git(root, "add", "second.py")
    calls: list[tuple[str, ...]] = []

    def coordination(_root: Path, *arguments: str) -> dict[str, object]:
        calls.append(arguments)
        if arguments[0] == "status":
            return {
                "agents": [
                    {
                        "id": "agent-existing",
                        "state": "active",
                        "branch": "codex/example",
                        "worktree": str(root),
                    }
                ],
                "claims": [
                    {
                        "id": "claim-first",
                        "agentId": "agent-existing",
                        "status": "active",
                        "scopes": ["first.py"],
                    }
                ],
            }
        if arguments[0] == "release":
            return {"ok": True}
        assert arguments[0] == "claim"
        scopes = [
            arguments[index + 1]
            for index, value in enumerate(arguments)
            if value == "--scope"
        ]
        return {
            "ok": True,
            "claim": {
                "id": "claim-union",
                "agentId": "agent-existing",
                "scopes": scopes,
            },
        }

    monkeypatch.setattr(guard, "coordination_call", coordination)
    binding = guard.ensure_development_claim(root)

    assert binding.claim_id == "claim-union"
    assert binding.scopes == ("first.py", "second.py")
    assert any(item[:2] == ("release", "--claim-id") for item in calls)


def test_reference_transaction_blocks_main_without_permit(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old_sha = _git(root, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(guard.ClaimGuardError, match="main_update_permit_required"):
        guard.check_reference_transaction(
            root,
            "prepared",
            io.StringIO(f"{old_sha} {'1' * 40} refs/heads/main\n"),
        )


def test_reference_transaction_allows_other_refs_without_permit(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    guard.check_reference_transaction(
        root,
        "prepared",
        io.StringIO(f"{old_sha} {'1' * 40} refs/heads/topic\n"),
    )


def test_main_permit_is_exact_expiring_and_one_use(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    old_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    new_sha = "1" * 40
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    guard.issue_main_permit(
        root,
        old_sha=old_sha,
        new_sha=new_sha,
        integration_claim_id="claim-int",
        now=now,
    )

    guard.check_reference_transaction(
        root,
        "prepared",
        io.StringIO(f"{old_sha} {new_sha} refs/heads/main\n"),
        now=now,
    )
    guard.check_reference_transaction(
        root,
        "committed",
        io.StringIO(f"{old_sha} {new_sha} refs/heads/main\n"),
        now=now,
    )
    with pytest.raises(guard.ClaimGuardError, match="main_update_permit_required"):
        guard.check_reference_transaction(
            root,
            "prepared",
            io.StringIO(f"{old_sha} {new_sha} refs/heads/main\n"),
            now=now,
        )

    guard.issue_main_permit(
        root,
        old_sha=old_sha,
        new_sha=new_sha,
        integration_claim_id="claim-int",
        now=now,
    )
    with pytest.raises(guard.ClaimGuardError, match="main_update_permit_mismatch"):
        guard.check_reference_transaction(
            root,
            "prepared",
            io.StringIO(f"{old_sha} {'2' * 40} refs/heads/main\n"),
            now=now,
        )
    with pytest.raises(guard.ClaimGuardError, match="main_update_permit_expired"):
        guard.check_reference_transaction(
            root,
            "prepared",
            io.StringIO(f"{old_sha} {new_sha} refs/heads/main\n"),
            now=now + timedelta(minutes=2),
        )


def test_real_hook_blocks_manual_main_update_and_accepts_one_permit(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    (root / "scripts").mkdir()
    shutil.copy2(project_root / "scripts" / "git_claim_guard.py", root / "scripts")
    hooks = root / ".githooks"
    hooks.mkdir()
    shutil.copy2(project_root / ".githooks" / "reference-transaction", hooks)
    _git(root, "switch", "-c", "codex/example")
    (root / "README.md").write_text("next\n", encoding="utf-8")
    _git(root, "add", "README.md")
    env = {**os.environ, "VIBELUTION_HOOK_PYTHON": sys.executable}
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "next", env=env)
    new_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    old_sha = _git(root, "rev-parse", "main").stdout.strip()
    _git(root, "config", "core.hooksPath", ".githooks")

    blocked = _git(
        root, "update-ref", "refs/heads/main", new_sha, old_sha, env=env, check=False
    )
    assert blocked.returncode != 0
    assert "main_update_permit_required" in blocked.stderr

    guard.issue_main_permit(
        root,
        old_sha=old_sha,
        new_sha=new_sha,
        integration_claim_id="claim-int",
    )
    _git(root, "update-ref", "refs/heads/main", new_sha, old_sha, env=env)
    replay = _git(
        root, "update-ref", "refs/heads/main", old_sha, new_sha, env=env, check=False
    )
    assert replay.returncode != 0


def test_closeout_merge_issues_exact_main_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = closeout.CloseoutContext(
        main_root=tmp_path / "main",
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(gate, "git_lines", lambda *_args: [])
    monkeypatch.setattr(
        gate,
        "rev_parse",
        lambda root, _revision: (
            "new-sha" if Path(root) == context.task_root else "old-sha"
        ),
    )
    monkeypatch.setattr(
        closeout.claim_guard,
        "issue_main_permit",
        lambda root, **kwargs: calls.append(("permit", (Path(root), kwargs))),
    )
    monkeypatch.setattr(
        closeout.claim_guard,
        "clear_main_permit",
        lambda root: calls.append(("clear", Path(root))),
    )
    monkeypatch.setattr(
        gate,
        "run_process",
        lambda argv, root: (
            calls.append(("merge", (argv, Path(root))))
            or subprocess.CompletedProcess(argv, 0, "", "")
        ),
    )

    assert (
        closeout.merge_ff_only(context, integration_claim_id="claim-int") == "new-sha"
    )
    assert calls == [
        (
            "permit",
            (
                context.main_root,
                {
                    "old_sha": "old-sha",
                    "new_sha": "new-sha",
                    "integration_claim_id": "claim-int",
                },
            ),
        ),
        ("merge", (["git", "merge", "--ff-only", context.branch], context.main_root)),
        ("clear", context.main_root),
    ]


def test_closeout_identity_can_be_loaded_from_worktree_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = closeout.CloseoutContext(
        main_root=tmp_path / "main",
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )
    monkeypatch.setattr(
        closeout.claim_guard,
        "read_claim_binding",
        lambda _root: guard.ClaimBinding(
            claim_id="claim-auto",
            agent_id="agent-auto",
            branch=context.branch,
            worktree=str(context.task_root),
            scopes=("scripts/one.py",),
        ),
    )

    assert closeout.resolve_claim_identity(context, claim_id="", agent_id="") == (
        "claim-auto",
        "agent-auto",
    )
