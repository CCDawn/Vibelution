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


def _candidate(candidate: Path) -> None:
    candidate.mkdir(parents=True)
    (candidate / "agent.py").write_text("BASELINE = False\n", encoding="utf-8")
    (candidate / "tests").mkdir()
    (candidate / "tests" / "candidate_marker.py").write_text(
        "CANDIDATE = True\n",
        encoding="utf-8",
    )


def _changes() -> list[dict[str, str]]:
    return [
        {"path": "agent.py", "changeType": "modified"},
        {"path": "tests/candidate_marker.py", "changeType": "added"},
    ]


def test_integrate_candidate_creates_exact_clean_commit(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate(candidate)

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
    assert result["commitSha"] != base_commit
    assert result["changedFiles"] == ["agent.py", "tests/candidate_marker.py"]
    assert result["mechanism"] == "controlled_candidate_commit"
    assert _git(project, "status", "--porcelain=v1").stdout == ""
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = False\n"
    assert (project / "tests" / "candidate_marker.py").read_text(
        encoding="utf-8"
    ) == "CANDIDATE = True\n"
    assert "swte-123" in _git(project, "show", "-s", "--format=%B").stdout
    assert Path(result["rollbackManifestPath"]).exists()


def test_integrate_candidate_rejects_any_dirty_target_before_writes(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate(candidate)
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


def test_integrate_candidate_rejects_head_drift(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate(candidate)
    (project / "drift.txt").write_text("drift\n", encoding="utf-8")
    _git(project, "add", "drift.txt")
    _git(project, "commit", "-m", "advance main")

    with pytest.raises(service.CandidateIntegrationError, match="HEAD 已偏离"):
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


def test_integrate_candidate_restores_clean_tree_when_commit_fails(tmp_path, monkeypatch):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    _candidate(candidate)
    original_run_git = service.git_process.run_git

    def fail_commit(args, **kwargs):
        if list(args[:1]) == ["commit"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="synthetic commit failure",
            )
        return original_run_git(args, **kwargs)

    monkeypatch.setattr(service.git_process, "run_git", fail_commit)

    with pytest.raises(service.CandidateIntegrationError, match="Git 提交失败"):
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
    _candidate(candidate)
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
