from __future__ import annotations

import subprocess
from pathlib import Path

from core.infrastructure.git_fileread import read_git_identity
from core.launcher import freshness as launcher_freshness


def test_freshness_is_current_when_start_matches_head(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: {"commit": "aaa111", "branch": "main"})

    launcher_freshness.capture_launcher_start_identity()
    payload = launcher_freshness.get_launcher_freshness()

    assert payload["current"] is True
    assert payload["runningCommit"] == "aaa111"
    assert payload["headCommit"] == "aaa111"
    assert "已是最新" in payload["label"]


def test_freshness_is_stale_when_head_moves_after_start(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    states = iter(
        [
            {"commit": "aaa111bbbb", "branch": "main"},
            {"commit": "ccc222dddd", "branch": "main"},
        ]
    )
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: next(states))

    launcher_freshness.capture_launcher_start_identity()
    payload = launcher_freshness.get_launcher_freshness()

    assert payload["current"] is False
    assert payload["runningShort"] == "aaa111bbbb"[:12]
    assert payload["headShort"] == "ccc222dddd"[:12]
    assert "落后本地 main" in payload["label"]


def test_freshness_retries_when_first_git_identity_is_empty(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()
    # One identity capture per freshness read; the start identity reuses it.
    states = iter(
        [
            {"commit": "", "branch": ""},
            {"commit": "aaa111bbbbcc", "branch": "main"},
        ]
    )
    monkeypatch.setattr(launcher_freshness, "_git_identity", lambda: next(states))

    first = launcher_freshness.get_launcher_freshness()
    assert first["current"] is None
    assert first["label"] == "Launcher 版本未知"

    second = launcher_freshness.get_launcher_freshness()
    assert second["current"] is True
    assert second["runningCommit"] == "aaa111bbbbcc"
    assert "已是最新" in second["label"]


def test_freshness_first_read_captures_head_identity_once(monkeypatch):
    """One HEAD capture serves both the start identity and the head comparison."""

    launcher_freshness.reset_launcher_start_identity_for_tests()
    calls: list[int] = []

    def identity() -> dict[str, str]:
        calls.append(1)
        return {"commit": "aaa111bbbbcc", "branch": "main"}

    monkeypatch.setattr(launcher_freshness, "_git_identity", identity)

    payload = launcher_freshness.get_launcher_freshness()

    assert len(calls) == 1
    assert payload["current"] is True
    assert payload["runningCommit"] == "aaa111bbbbcc"
    assert payload["headCommit"] == "aaa111bbbbcc"
    assert payload["runningBranch"] == "main"
    assert payload["startedAt"]


def test_capture_start_identity_reuses_caller_supplied_head(monkeypatch):
    launcher_freshness.reset_launcher_start_identity_for_tests()

    def fail() -> dict[str, str]:
        raise AssertionError("a supplied head must not trigger a second git capture")

    monkeypatch.setattr(launcher_freshness, "_git_identity", fail)
    supplied = {"commit": "bbb222", "branch": "codex/lane"}

    started = launcher_freshness.capture_launcher_start_identity(captured_head=supplied)

    assert started["commit"] == "bbb222"
    assert started["branch"] == "codex/lane"
    assert started["startedAt"]
    # The caller's dict is copied, not adopted.
    assert "startedAt" not in supplied


# --- pure file-read identity fast path -------------------------------------


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "freshness@example.local")
    _git(root, "config", "user.name", "Freshness Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def _forbid_git_children(monkeypatch) -> None:
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)

    def no_git(*_args, **_kwargs):
        raise AssertionError("the file-read fast path must not spawn a git child")

    monkeypatch.setattr(launcher_freshness.git_process, "run_git", no_git)


def test_git_identity_reads_plain_repo_from_files_without_git_children(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "plain")
    expected_commit = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(launcher_freshness, "PROJECT_ROOT", repo)
    _forbid_git_children(monkeypatch)

    identity = launcher_freshness._git_identity()

    assert identity == {"commit": expected_commit, "branch": "main"}
    assert read_git_identity(repo) == {"headCommit": expected_commit, "branchName": "main"}


def test_git_identity_falls_back_to_git_when_refs_are_packed_only(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "packed")
    expected_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "pack-refs", "--all")
    loose_ref = repo / ".git" / "refs" / "heads" / "main"
    if loose_ref.exists():
        loose_ref.unlink()
    assert "refs/heads/main" in (repo / ".git" / "packed-refs").read_text(encoding="utf-8")
    assert _git(repo, "rev-parse", "HEAD") == expected_commit
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(launcher_freshness, "PROJECT_ROOT", repo)

    # The file read cannot resolve a packed-only ref: it steps aside instead of
    # guessing, and the git-command path still answers correctly.
    assert read_git_identity(repo) is None
    assert launcher_freshness._git_identity() == {"commit": expected_commit, "branch": "main"}


def test_git_identity_detached_head_keeps_the_head_branch_label(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path / "detached")
    _git(repo, "checkout", "--detach", "HEAD")
    expected_commit = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "branch", "--show-current") == ""
    monkeypatch.setattr(launcher_freshness, "PROJECT_ROOT", repo)
    _forbid_git_children(monkeypatch)

    identity = launcher_freshness._git_identity()

    # The file read reports branchName="" for a detached HEAD; the launcher
    # maps it to "HEAD" exactly like the `branch --show-current` path does.
    assert read_git_identity(repo) == {"headCommit": expected_commit, "branchName": ""}
    assert identity == {"commit": expected_commit, "branch": "HEAD"}


def test_git_identity_outside_a_repo_stays_unknown(tmp_path, monkeypatch):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(launcher_freshness, "PROJECT_ROOT", plain)

    assert read_git_identity(plain) is None
    assert launcher_freshness._git_identity() == {"commit": "", "branch": ""}
