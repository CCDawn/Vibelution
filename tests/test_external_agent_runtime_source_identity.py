import os
import subprocess

import pytest

from core.external_agent import runtime_source_identity as identity
from core.infrastructure.no_console_git import run_git


@pytest.fixture
def repository(tmp_path, monkeypatch):
    # Hooks may run pytest with the real checkout's GIT_DIR/GIT_INDEX_FILE.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    def git(*args):
        result = run_git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                          "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={tmp_path / '.git' / 'empty-hooks'}", *args], cwd=tmp_path, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    git("init")
    (tmp_path / ".git" / "empty-hooks").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "service.py").write_text("VALUE = 1\n")
    git("add", ".")
    git("commit", "-m", "runtime")
    return tmp_path, git, git("rev-parse", "HEAD")


@pytest.mark.parametrize("path", ["scripts/install_windows.ps1", "web/src/page.tsx", "docs/guide.md", "tests/test_service.py"])
def test_non_runtime_commits_keep_backend_sources_equivalent(repository, path):
    root, git, running = repository
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    git("add", ".")
    git("commit", "-m", "non-runtime")
    assert identity.runtime_sources_match(root, running, git("rev-parse", "HEAD"))


@pytest.mark.parametrize("path", ["core/service.py", "tools/action.py", "config/defaults.py", "scripts/runtime.py", "requirements.txt", "AGENTS.md", "assets/model.svg"])
def test_runtime_or_unknown_changes_remain_blocked(repository, path):
    root, git, running = repository
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n")
    git("add", ".")
    git("commit", "-m", "runtime changed")
    assert not identity.runtime_sources_match(root, running, git("rev-parse", "HEAD"))


@pytest.mark.parametrize("mode", ["unstaged", "staged", "untracked", "deleted"])
def test_local_runtime_changes_cannot_hide_behind_a_non_runtime_commit(repository, mode):
    root, git, running = repository
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("docs\n")
    git("add", ".")
    git("commit", "-m", "docs")
    head = git("rev-parse", "HEAD")
    if mode == "untracked":
        (root / "core" / "new.py").write_text("VALUE = 2\n")
    elif mode == "deleted":
        (root / "core" / "service.py").unlink()
    else:
        (root / "core" / "service.py").write_text("VALUE = 2\n")
        if mode == "staged":
            git("add", ".")
    assert not identity.runtime_sources_match(root, running, head)


@pytest.mark.parametrize("output", ["docs/x\0core/service.py\0", "docs/x", "docs/../core/x\0", "/docs/x\0", "docs\\x\0", "x" * (64 * 1024 + 1)],
                         ids=["mixed-runtime", "unterminated", "traversal", "absolute", "backslash", "oversize"])
def test_failed_or_malformed_git_evidence_is_not_equivalence(tmp_path, monkeypatch, output):
    monkeypatch.setattr(identity, "run_git", lambda *_a, **_k: subprocess.CompletedProcess([], 0, output, ""))
    assert not identity.runtime_sources_match(tmp_path, "a" * 40, "b" * 40)


def test_missing_history_and_git_timeout_remain_blocked(repository, monkeypatch):
    root, _, running = repository
    assert not identity.runtime_sources_match(root, "0" * 40, running)
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("git", 1)
    monkeypatch.setattr(identity, "run_git", timeout)
    assert not identity.runtime_sources_match(root, "a" * 40, "b" * 40)


def test_revision_strings_cannot_inject_git_options(tmp_path):
    assert not identity.runtime_sources_match(tmp_path, "--output=elsewhere", "b" * 40)
