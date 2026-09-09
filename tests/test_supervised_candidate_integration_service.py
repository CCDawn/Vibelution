from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from core.web.services import supervised_candidate_integration_service as service


@pytest.fixture(autouse=True)
def isolated_validation_authority(monkeypatch, tmp_path):
    install_validation_authority(monkeypatch, tmp_path)


def install_validation_authority(monkeypatch, tmp_path):
    """Model passed validation; keep the production permit and Git merge real."""
    def binding(candidate):
        branch = _git(candidate, "branch", "--show-current").stdout.strip()
        if not branch.startswith("codex/"):
            branch = "codex/isolated-candidate"
            _git(candidate, "switch", "-c", branch)
        return SimpleNamespace(branch=branch, worktree=str(candidate), claim_id="development-test", agent_id="test-owner")
    monkeypatch.setattr(service.git_claim_guard, "read_claim_binding", binding)
    monkeypatch.setattr(service.task_closeout, "validate_development_claim", lambda *a, **kw: None)
    monkeypatch.setattr(service.task_closeout, "discover_manifest", lambda *a: tmp_path / "validated.json")
    monkeypatch.setattr(service.local_quality_gate, "verify_manifest", lambda *a: SimpleNamespace(outcome="passed", manifest_path=tmp_path / "validated.json"))
    monkeypatch.setattr(service.task_closeout, "acquire_integration_claim_with_retry", lambda *a, **kw: "integration-test")
    monkeypatch.setattr(service.task_closeout, "release_claim", lambda *a, **kw: None)
    monkeypatch.setattr(service.task_closeout, "complete_agent", lambda *a, **kw: None)


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


def test_failed_validation_never_acquires_integration_permission(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    _candidate_worktree(project, candidate)
    failed = SimpleNamespace(outcome="failed", manifest_path=tmp_path / "failed.json")
    monkeypatch.setattr(service.local_quality_gate, "verify_manifest", lambda *a: failed)
    monkeypatch.setattr(service.local_quality_gate, "run_closeout", lambda *a: failed)
    monkeypatch.setattr(service.task_closeout, "acquire_integration_claim_with_retry", lambda *a, **kw: pytest.fail("validation must precede permission"))
    with pytest.raises(service.CandidateIntegrationError, match="验证未通过"):
        service._merge_validated_candidate(project, candidate, expected_head=base, candidate_head=_git(candidate, "rev-parse", "HEAD").stdout.strip())
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base


def test_changed_manifest_under_lease_releases_lease_without_merging(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    _candidate_worktree(project, candidate)
    calls = []
    results = iter(["passed", "stale_main"])
    monkeypatch.setattr(service.local_quality_gate, "verify_manifest", lambda *a: SimpleNamespace(
        outcome=next(results), manifest_path=tmp_path / "manifest.json",
    ))
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("changed evidence must not merge"))
    monkeypatch.setattr(service.task_closeout, "release_claim", lambda *a, **kw: calls.append(a[1]))
    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service._merge_validated_candidate(project, candidate, expected_head=base, candidate_head=_git(candidate, "rev-parse", "HEAD").stdout.strip())
    assert calls == ["integration-test"]
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base


def test_cleanup_failure_does_not_hide_a_completed_merge(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    candidate_head = _candidate_worktree(project, candidate)
    def release(*args, **kwargs):
        raise RuntimeError("cleanup unavailable")
    monkeypatch.setattr(service.task_closeout, "release_claim", release)
    result = service.integrate_candidate(
        project_root=project, candidate_root=candidate, changed_files=_changes(),
        expected_head=base, expected_variant_id="variant-123", run_id="swte-cleanup",
        manifest_root=tmp_path / "manifests",
    )
    assert result["commitSha"] == candidate_head
    assert result["governanceCleanup"]["status"] == "pending"
    assert not service.git_claim_guard._permit_path(project).exists()


def test_candidate_changed_during_validation_is_not_promoted(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    frozen = _candidate_worktree(project, candidate)
    def acquire(*args, **kwargs):
        (candidate / "agent.py").write_text("UNREVIEWED = True\n", encoding="utf-8")
        _git(candidate, "add", "agent.py")
        _git(candidate, "commit", "-m", "unreviewed change")
        return "integration-test"
    monkeypatch.setattr(service.task_closeout, "acquire_integration_claim_with_retry", acquire)
    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service._merge_validated_candidate(project, candidate, expected_head=base, candidate_head=frozen)
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base


def test_branch_advancing_after_validation_only_merges_approved_sha(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    approved = _candidate_worktree(project, candidate)
    merge = service.task_closeout.merge_ff_only

    def advance_then_merge(context, **kwargs):
        (candidate / "agent.py").write_text("UNREVIEWED = True\n", encoding="utf-8")
        _git(candidate, "add", "agent.py")
        _git(candidate, "commit", "-m", "late unreviewed change")
        return merge(context, **kwargs)

    monkeypatch.setattr(service.task_closeout, "merge_ff_only", advance_then_merge)
    service._merge_validated_candidate(project, candidate, expected_head=base, candidate_head=approved)
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == approved
    assert _git(candidate, "rev-parse", "HEAD").stdout.strip() != approved
    assert (project / "agent.py").read_text(encoding="utf-8") == "BASELINE = False\n"


def test_mismatched_worktree_binding_cannot_integrate(tmp_path, monkeypatch):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    approved = _candidate_worktree(project, candidate)
    monkeypatch.setattr(service.git_claim_guard, "read_claim_binding", lambda *a: SimpleNamespace(
        branch="codex/supervised-candidate", worktree=str(tmp_path / "another-candidate"),
        claim_id="development-test", agent_id="test-owner",
    ))
    with pytest.raises(service.CandidateIntegrationError, match="归属记录不匹配"):
        service._merge_validated_candidate(project, candidate, expected_head=base, candidate_head=approved)
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base


def test_integrate_candidate_creates_exact_clean_commit(tmp_path):
    project = tmp_path / "project"
    candidate = tmp_path / "candidate"
    base_commit = _init_repo(project)
    candidate_head = _candidate_worktree(project, candidate)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    guard = Path(service.git_claim_guard.__file__).resolve().as_posix()
    (hooks / "reference-transaction").write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{guard}" reference-transaction --repo "{project.as_posix()}" --phase "$1"\n',
        encoding="utf-8",
    )
    _git(project, "config", "core.hooksPath", hooks.as_posix())

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
    original_run_git = service.local_quality_gate.run_process

    def fail_merge(args, *pos, **kwargs):
        if list(args[:2]) == ["git", "merge"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                1,
                stdout="",
                stderr="synthetic merge failure",
            )
        return original_run_git(args, *pos, **kwargs)

    monkeypatch.setattr(service.local_quality_gate, "run_process", fail_merge)

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
