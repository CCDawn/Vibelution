from __future__ import annotations

import subprocess
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts import git_hook_install as installer
from scripts import git_claim_guard as guard
from scripts import local_quality_gate as gate

SOURCE = Path(__file__).resolve().parents[1]

# Frozen legacy permit/ref protocol; unrelated development-claim code is omitted.
LEGACY_GUARD = '''import json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def permit_path(root):
    common = subprocess.check_output(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root, text=True).strip()
    return Path(common) / "vibelution-cache/main-ref-permit.json"

def issue_main_permit(root, *, old_sha, new_sha, integration_claim_id):
    now = datetime.now(timezone.utc)
    path = permit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 1, "oldSha": old_sha, "newSha": new_sha,
        "integrationClaimId": integration_claim_id, "expiresAt": (now + timedelta(seconds=60)).isoformat()}))

if __name__ == "__main__":
    root = sys.argv[sys.argv.index("--repo") + 1]
    phase = sys.argv[sys.argv.index("--phase") + 1]
    updates = [line.split() for line in sys.stdin if line.split()[-1:] == ["refs/heads/main"]]
    for old, new, ref in updates:
        if old == new:
            continue
        path = permit_path(root)
        permit = json.loads(path.read_text())
        assert [old, new] == [permit["oldSha"], permit["newSha"]]
        if phase in ("prepared", "preparing"):
            assert datetime.now(timezone.utc) <= datetime.fromisoformat(permit["expiresAt"])
        elif phase in ("committed", "aborted"):
            path.unlink(missing_ok=True)
'''


def git(root: Path, *args: str, check: bool = True, input_text: str | None = None):
    env = gate.git_hook_isolated_environment()
    env["VIBELUTION_HOOK_PYTHON"] = sys.executable
    return subprocess.run(
        ["git", *args], cwd=root, env=env, capture_output=True, text=True,
        encoding="utf-8", check=check, input=input_text,
    )


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Human")
    git(root, "config", "user.email", "human@example.com")
    git(root, "commit", "--allow-empty", "-m", "human base")
    return root


@pytest.mark.parametrize("operation", ["update-ref", "fast-forward"])
def test_shared_guard_blocks_real_old_worktree_and_checked_out_old_guard(tmp_path: Path, operation: str) -> None:
    root = repo(tmp_path)
    legacy = LEGACY_GUARD
    for path, data in {
        "scripts/__init__.py": "",
        "scripts/git_claim_guard.py": legacy,
        "scripts/claim_dormancy.py": (SOURCE / "scripts/claim_dormancy.py").read_text(encoding="utf-8"),
        ".githooks/reference-transaction": (SOURCE / ".githooks/reference-transaction").read_text(encoding="utf-8"),
    }.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
    git(root, "add", "scripts", ".githooks")
    git(root, "commit", "-m", "legacy tooling")
    old_worktree = tmp_path / "old-task"
    git(root, "worktree", "add", str(old_worktree), "-b", "codex/old-task")
    if operation == "fast-forward":
        (root / "scripts/git_claim_guard.py").write_bytes((SOURCE / "scripts/git_claim_guard.py").read_bytes())
        git(root, "add", "scripts/git_claim_guard.py")
        git(root, "commit", "-m", "current guard")
        git(old_worktree, "merge", "--ff-only", "main")
        (old_worktree / "scripts/git_claim_guard.py").write_text(legacy, encoding="utf-8")
        git(old_worktree, "add", "scripts/git_claim_guard.py")
    old_sha = git(root, "rev-parse", "main").stdout.strip()
    (old_worktree / "feature.txt").write_text("keep all task code\n", encoding="utf-8")
    git(old_worktree, "add", "feature.txt")
    git(old_worktree, "commit", "--author", "Cursor <cursoragent@cursor.com>", "-m", "old task work")
    candidate = git(old_worktree, "rev-parse", "HEAD").stdout.strip()
    git(root, "update-ref", "refs/vibelution-backups/preserved", old_sha)
    installer.install_hooks(root)
    env = gate.git_hook_isolated_environment()
    # Load the old package in a separate interpreter, as an old task would.
    issued = subprocess.run(
        [sys.executable, "-c", "from scripts.git_claim_guard import issue_main_permit; "
         f"issue_main_permit({str(root)!r}, old_sha={old_sha!r}, new_sha={candidate!r}, integration_claim_id='legacy')"],
        cwd=old_worktree, env=env, capture_output=True, text=True,
    )
    assert issued.returncode == 0, issued.stderr
    result = (
        git(old_worktree, "update-ref", "refs/heads/main", candidate, old_sha, check=False)
        if operation == "update-ref" else git(root, "merge", "--ff-only", candidate, check=False)
    )
    assert result.returncode != 0
    assert "incoming_ai_attribution" in result.stderr
    assert git(root, "rev-parse", "main").stdout.strip() == old_sha
    assert git(root, "rev-parse", "refs/vibelution-backups/preserved").stdout.strip() == old_sha
    assert git(root, "show", f"{candidate}:feature.txt").stdout == "keep all task code\n"


@pytest.mark.parametrize("name", ["pre-commit", "commit-msg", "pre-push", "post-merge"])
def test_other_hooks_delegate_to_current_checkout_with_original_io(tmp_path: Path, name: str) -> None:
    root = repo(tmp_path)
    task = tmp_path / "task"
    git(root, "worktree", "add", str(task), "-b", "codex/task")
    hooks = task / ".githooks"
    hooks.mkdir()
    hook = hooks / name
    hook.write_text('#!/bin/sh\nprintf "task|%s|%s\\n" "$1" "$(cat)"\nexit 7\n', encoding="utf-8")
    hook.chmod(0o755)
    shared = installer.install_hooks(root)
    shell = shutil.which("sh") or str(Path(shutil.which("git") or "git").parent.parent / "bin/sh.exe")
    result = subprocess.run(
        [shell, str(shared / name), "argument with spaces"], cwd=task,
        env={**gate.git_hook_isolated_environment(), "VIBELUTION_HOOK_PYTHON": sys.executable}, input="original stdin",
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 7
    assert "task|argument with spaces|original stdin" in result.stdout + result.stderr


def test_installation_is_complete_idempotent_and_checks_damage(tmp_path: Path) -> None:
    root = repo(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: installer.install_hooks(root), range(2)))
    assert paths[0] == paths[1]
    assert installer.check_installation(root)["ok"] is True
    old_sha = git(root, "rev-parse", "main").stdout.strip()
    candidate = git(root, "commit-tree", f"{old_sha}^{{tree}}", "-p", old_sha, "-m", "human").stdout.strip()
    guard.issue_main_permit(root, old_sha=old_sha, new_sha=candidate, integration_claim_id="human")
    (paths[0].parent / "scripts/claim_dormancy.py").unlink()
    assert installer.check_installation(root)["ok"] is False
    blocked = git(root, "update-ref", "refs/heads/main", candidate, old_sha, check=False)
    assert blocked.returncode != 0
    assert "claim_dormancy" in blocked.stderr
    assert git(root, "rev-parse", "main").stdout.strip() == old_sha
    installer.install_hooks(root)
    assert installer.check_installation(root)["ok"] is True
    git(root, "update-ref", "refs/heads/main", candidate, old_sha)
    assert git(root, "rev-parse", "main").stdout.strip() == candidate


def test_guard_source_update_is_detected_and_installed_as_a_new_snapshot(tmp_path: Path) -> None:
    root = repo(tmp_path)
    source = tmp_path / "source"
    for name in ("scripts/git_claim_guard.py", "scripts/claim_dormancy.py", "scripts/git_history_bridge.py", "scripts/git_hook_dispatch.py", ".githooks/reference-transaction"):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((SOURCE / name).read_bytes())
    old_hooks = installer.install_hooks(root, source)
    guard_file = source / "scripts/git_claim_guard.py"
    guard_file.write_bytes(guard_file.read_bytes() + b"\n# new guard revision\n")
    assert installer.check_installation(root, source)["ok"] is False
    new_hooks = installer.install_hooks(root, source)
    assert new_hooks != old_hooks
    assert installer.check_installation(root, source)["ok"] is True
    assert old_hooks.is_dir()


def test_failed_installation_preserves_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    git(root, "config", "core.hooksPath", ".githooks")
    monkeypatch.setattr(installer, "_write_atomic", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        installer.install_hooks(root)
    assert git(root, "config", "--get", "core.hooksPath").stdout.strip() == ".githooks"


def test_shared_precommit_keeps_checkout_body_but_uses_frozen_claim_calculator(tmp_path: Path) -> None:
    from scripts.git_hook_dispatch import dispatch

    root = repo(tmp_path)
    (root / ".githooks").mkdir()
    (root / "scripts").mkdir()
    (root / "scripts/git_claim_guard.py").write_text("raise RuntimeError('legacy claim calculator ran')\n")
    hook = root / ".githooks/pre-commit"
    hook.write_text(
        '#!/bin/sh\nrepo_root=$(git rev-parse --show-toplevel)\n'
        f'"{Path(sys.executable).as_posix()}" "$repo_root/scripts/git_claim_guard.py" ensure-claim --repo "$repo_root"\n'
        'printf "checkout-specific-check\\n" > "$repo_root/checkout-check.txt"\n',
        encoding="utf-8",
    )
    original = hook.read_bytes()
    runtime = tmp_path / "shared runtime"
    (runtime / "scripts").mkdir(parents=True)
    (runtime / "scripts/git_claim_guard.py").write_text(
        'from pathlib import Path\nimport sys\nPath(sys.argv[-1], "shared-check.txt").write_text("frozen")\n',
        encoding="utf-8",
    )
    assert dispatch(root, runtime, []) == 0
    assert (root / "shared-check.txt").read_text() == "frozen"
    assert (root / "checkout-check.txt").read_text().strip() == "checkout-specific-check"
    assert hook.read_bytes() == original
