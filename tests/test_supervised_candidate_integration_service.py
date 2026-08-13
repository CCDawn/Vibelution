from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.web.services import supervised_candidate_integration_service as service


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "supervised@example.local")
    _git(repo, "config", "user.name", "Supervised Integration")
    (repo / "agent.py").write_text("BASELINE = True\n", encoding="utf-8")
    _git(repo, "add", "agent.py")
    _git(repo, "commit", "-m", "baseline")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _candidate_worktree(project: Path, candidate: Path) -> str:
    _git(project, "worktree", "add", "-b", "codex/supervised-candidate", str(candidate))
    (candidate / "agent.py").write_text("BASELINE = False\n", encoding="utf-8")
    (candidate / "tests").mkdir(exist_ok=True)
    (candidate / "tests" / "candidate_marker.py").write_text(
        "CANDIDATE = True\n",
        encoding="utf-8",
    )
    _git(candidate, "add", "agent.py", "tests/candidate_marker.py")
    _git(candidate, "commit", "-m", "candidate tree")
    return _git(candidate, "rev-parse", "HEAD").stdout.strip()


def _changes() -> list[dict[str, str]]:
    return [
        {"path": "agent.py", "changeType": "modified"},
        {"path": "tests/candidate_marker.py", "changeType": "added"},
    ]


def test_integrate_candidate_creates_exact_clean_commit(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    candidate_head = _candidate_worktree(project, candidate)

    result = service.integrate_candidate(
        project_root=project,
        candidate_root=candidate,
        changed_files=_changes(),
        expected_head=base_commit,
        expected_variant_id="variant-123",
        run_id="swte-123",
        manifest_root=tmp_path / "manifests",
    )

    assert result["status"] == "committed"
    assert result["baseCommit"] == base_commit
    assert result["commitSha"] == _git(project, "rev-parse", "HEAD").stdout.strip()
    assert result["commitSha"] == candidate_head
    assert result["mechanism"] == "git_merge_ff"
    assert "agent.py" in result["changedFiles"]
    assert "tests/candidate_marker.py" in result["changedFiles"]
    assert _git(project, "status", "--porcelain=v1").stdout == ""
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = False\n"
    assert (project / "tests" / "candidate_marker.py").read_text(
        encoding="utf-8"
    ) == "CANDIDATE = True\n"
    assert Path(result["rollbackManifestPath"]).exists()


def test_integrate_candidate_rejects_any_dirty_target_before_writes(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate_worktree(project, candidate)
    (project / "unrelated.tmp").write_text("user data\n", encoding="utf-8")

    with pytest.raises(service.CandidateIntegrationError, match="主工作区必须完全干净"):
        service.integrate_candidate(
            project_root=project,
            candidate_root=candidate,
            changed_files=_changes(),
            expected_head=base_commit,
            expected_variant_id="variant-123",
            run_id="swte-123",
            manifest_root=tmp_path / "manifests",
        )

    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = True\n"
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base_commit


def test_integrate_candidate_freezes_uncommitted_candidate_then_ff(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _git(project, "worktree", "add", "-b", "codex/supervised-candidate", str(candidate))
    (candidate / "agent.py").write_text("BASELINE = False\n", encoding="utf-8")

    result = service.integrate_candidate(
        project_root=project,
        candidate_root=candidate,
        changed_files=[{"path": "agent.py", "changeType": "modified"}],
        expected_head=base_commit,
        expected_variant_id="variant-123",
        run_id="swte-123",
        manifest_root=tmp_path / "manifests",
    )

    assert result["mechanism"] == "git_merge_ff"
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = False\n"
    assert _git(candidate, "status", "--porcelain=v1", "--untracked-files=no").stdout == ""
    assert _git(project, "status", "--porcelain=v1").stdout == ""


def test_integrate_candidate_rejects_when_main_has_moved(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate_worktree(project, candidate)
    (project / "drift.txt").write_text("drift\n", encoding="utf-8")
    _git(project, "add", "drift.txt")
    _git(project, "commit", "-m", "advance main")
    advanced_head = _git(project, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service.integrate_candidate(
            project_root=project,
            candidate_root=candidate,
            changed_files=_changes(),
            expected_head=base_commit,
            expected_variant_id="variant-123",
            run_id="swte-123",
            manifest_root=tmp_path / "manifests",
        )

    assert _git(project, "rev-parse", "HEAD").stdout.strip() == advanced_head
    assert _git(project, "status", "--porcelain=v1").stdout == ""
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = True\n"
    assert (project / "drift.txt").read_text(encoding="utf-8") == "drift\n"
    assert not (project / "tests" / "candidate_marker.py").exists()
    assert not (tmp_path / "manifests").exists()


def test_integrate_candidate_restores_clean_tree_when_commit_fails(tmp_path, monkeypatch):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate_worktree(project, candidate)
    original_run_git = service.git_process.run_git

    def fail_merge(args, **kwargs):
        if list(args[:1]) == ["merge"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="synthetic merge failure",
            )
        return original_run_git(args, **kwargs)

    monkeypatch.setattr(service.git_process, "run_git", fail_merge)

    with pytest.raises(service.CandidateIntegrationError, match="synthetic merge failure"):
        service.integrate_candidate(
            project_root=project,
            candidate_root=candidate,
            changed_files=_changes(),
            expected_head=base_commit,
            expected_variant_id="variant-123",
            run_id="swte-123",
            manifest_root=tmp_path / "manifests",
        )

    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base_commit
    assert _git(project, "status", "--porcelain=v1").stdout == ""
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = True\n"
    assert not (project / "tests" / "candidate_marker.py").exists()


def test_revert_candidate_commit_creates_auditable_revert(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate_worktree(project, candidate)
    integrated = service.integrate_candidate(
        project_root=project,
        candidate_root=candidate,
        changed_files=_changes(),
        expected_head=base_commit,
        expected_variant_id="variant-123",
        run_id="swte-123",
        manifest_root=tmp_path / "manifests",
    )

    result = service.revert_candidate_commit(
        project_root=project,
        integration_commit=str(integrated["commitSha"]),
        run_id="swte-123",
    )

    assert result["status"] == "reverted"
    assert result["revertedCommit"] == integrated["commitSha"]
    assert result["revertCommit"] == _git(project, "rev-parse", "HEAD").stdout.strip()
    assert result["revertCommit"] != integrated["commitSha"]
    assert _git(project, "status", "--porcelain=v1").stdout == ""
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = True\n"
    assert not (project / "tests" / "candidate_marker.py").exists()
