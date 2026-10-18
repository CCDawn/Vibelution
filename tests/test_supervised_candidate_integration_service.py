from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path

import pytest

from core.web.services import supervised_candidate_integration_service as service
from scripts.task_closeout import complete_agent as _real_complete_agent, release_claim as _real_release_claim


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
        env=service.local_quality_gate.git_hook_isolated_environment(),
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


def _integration_args(tmp_path):
    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    approved = _candidate_worktree(project, candidate)
    return dict(project_root=project, candidate_root=candidate, changed_files=_changes(),
                expected_head=base, expected_variant_id="sha256:" + "a" * 64,
                run_id="recovery-run", manifest_root=tmp_path / "manifests",
                expected_candidate_commit=approved)


def test_prepare_freezes_exact_candidate_without_integrating(tmp_path, monkeypatch):
    from core.web.services.self_evolution_candidate_workspace import inspect_candidate_workspace

    project, candidate = tmp_path / "project", tmp_path / "candidate"
    base = _init_repo(project)
    _git(project, "worktree", "add", "-b", "codex/self-evolution-prepare", str(candidate))
    (candidate / "agent.py").write_text("BASELINE = False\n", encoding="utf-8")
    workspace = {"worktreePath": str(candidate), "branch": "codex/self-evolution-prepare", "baseCommit": base}
    inspected = inspect_candidate_workspace(project, workspace)
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("prepare must not merge"))
    monkeypatch.setattr(service.task_closeout, "acquire_integration_claim_with_retry", lambda *a, **kw: pytest.fail("prepare must not acquire integration"))

    result = service.prepare_candidate(project_root=project, candidate_root=candidate,
        changed_files=inspected["changedFiles"], expected_head=base,
        expected_variant_id=inspected["variantId"], run_id="prepare-run")

    assert result["headCommit"] == _git(candidate, "rev-parse", "HEAD").stdout.strip() != base
    assert result["variantId"] == inspected["variantId"]
    assert result["validationManifestPath"]
    assert _git(candidate, "status", "--porcelain=v1").stdout == ""
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == base


@pytest.mark.parametrize("drift", ["commit", "dirty"])
def test_exact_reviewed_sha_rejects_candidate_drift_before_merge(tmp_path, monkeypatch, drift):
    args = _integration_args(tmp_path)
    candidate = args["candidate_root"]
    (candidate / "agent.py").write_text("UNREVIEWED = True\n", encoding="utf-8")
    if drift == "commit":
        _git(candidate, "add", "agent.py")
        _git(candidate, "commit", "-m", "unreviewed")
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("must not merge drift"))
    with pytest.raises(service.CandidateIntegrationError, match="reviewed_candidate_changed"):
        service.integrate_candidate(**args)
    assert _git(args["project_root"], "rev-parse", "HEAD").stdout.strip() == args["expected_head"]


def test_admission_denial_never_merges_or_persists_an_intent(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    released = []

    @contextmanager
    def denied():
        raise RuntimeError("authorization revoked")
        yield

    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("denied guard must not merge"))
    monkeypatch.setattr(service.task_closeout, "release_claim", lambda *a, **kw: released.append(a[1]))
    with pytest.raises(service.CandidateIntegrationError, match="authorization revoked"):
        service.integrate_candidate(**args, admission_guard=denied)
    assert released == ["integration-test"]
    assert not service._integration_intent_path(args["project_root"], args["run_id"]).exists()
    assert _git(args["project_root"], "rev-parse", "HEAD").stdout.strip() == args["expected_head"]


def test_intent_is_durable_only_inside_admitted_merge(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    inside = False
    merge = service.task_closeout.merge_ff_only
    intent_path = service._integration_intent_path(args["project_root"], args["run_id"])

    @contextmanager
    def guard():
        nonlocal inside
        assert not intent_path.exists()
        inside = True
        try:
            yield
        finally:
            inside = False

    def checked_merge(*a, **kw):
        import json
        assert inside and intent_path.exists()
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        assert intent["developmentBinding"] == {"claimId": "development-test", "agentId": "test-owner",
                                                "branch": "codex/supervised-candidate"}
        assert intent["integrationClaimId"] == "integration-test"
        assert kw["target_sha"] == args["expected_candidate_commit"]
        return merge(*a, **kw)

    monkeypatch.setattr(service.task_closeout, "merge_ff_only", checked_merge)
    result = service.integrate_candidate(**args, admission_guard=guard)
    assert result["commitSha"] == args["expected_candidate_commit"]
    assert ":" not in Path(result["rollbackManifestPath"]).name


@pytest.mark.parametrize("failure", ["manifest", "caller_result"])
def test_completed_merge_recovers_without_guard_validation_or_second_merge(tmp_path, monkeypatch, failure):
    args = _integration_args(tmp_path)
    write_manifest = service._write_manifest
    if failure == "manifest":
        def fail_manifest(*a, **kw):
            raise OSError("manifest storage unavailable")
        monkeypatch.setattr(service, "_write_manifest", fail_manifest)
        with pytest.raises(OSError, match="manifest storage unavailable"):
            service.integrate_candidate(**args)
        monkeypatch.setattr(service, "_write_manifest", write_manifest)
    else:
        # The caller loses its own result after this irreversible Git advance.
        service.integrate_candidate(**args)
    project = args["project_root"]
    approved = args["expected_candidate_commit"]
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == approved
    _git(project, "worktree", "remove", str(args["candidate_root"]))
    (project / "later.txt").write_text("later owner\n", encoding="utf-8")
    _git(project, "add", "later.txt")
    _git(project, "commit", "-m", "later owner")
    later = _git(project, "rev-parse", "HEAD").stdout.strip()
    reflog_before = service._main_reflog_path(project).read_bytes()
    monkeypatch.setattr(service, "_validate_managed_candidate", lambda *a: pytest.fail("completed fact needs no validation"))
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("must not merge twice"))

    def revoked_guard():
        pytest.fail("completed fact needs no renewed admission")

    recovered = service.integrate_candidate(**args, admission_guard=revoked_guard)
    assert recovered["commitSha"] == approved
    assert recovered["baseCommit"] == args["expected_head"]
    assert recovered["governanceCleanup"]["recovered"] is True
    assert Path(recovered["rollbackManifestPath"]).is_file()
    assert _git(project, "rev-parse", "HEAD").stdout.strip() == later
    assert service._main_reflog_path(project).read_bytes() == reflog_before


def test_existing_ancestor_without_this_runs_intent_is_not_recovered(tmp_path):
    args = _integration_args(tmp_path)
    _git(args["project_root"], "merge", "--ff-only", args["expected_candidate_commit"])
    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service.integrate_candidate(**args)


def test_failed_merge_intent_does_not_approve_unrelated_main_progress(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    def fail_merge(*a, **kw):
        raise RuntimeError("merge unavailable")
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", fail_merge)
    with pytest.raises(service.CandidateIntegrationError, match="merge unavailable"):
        service.integrate_candidate(**args)
    project = args["project_root"]
    (project / "unrelated.txt").write_text("other\n", encoding="utf-8")
    _git(project, "add", "unrelated.txt")
    _git(project, "commit", "-m", "unrelated")
    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service.integrate_candidate(**args)


@pytest.mark.parametrize("field", ["expected_head", "expected_candidate_commit", "expected_variant_id", "candidate_root", "run_id", "changed_files"])
def test_recovery_cannot_rebind_completed_intent(tmp_path, monkeypatch, field):
    args = _integration_args(tmp_path)
    service.integrate_candidate(**args)
    args[field] = ({"expected_head": "b" * 40, "expected_candidate_commit": "c" * 40,
                    "expected_variant_id": "another-variant", "candidate_root": tmp_path / "another",
                    "run_id": "another-run", "changed_files": [{"path": "other.py"}]}[field])
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("rebinding must not merge"))
    with pytest.raises(service.CandidateIntegrationError, match="integration_intent_mismatch|stale_main"):
        service.integrate_candidate(**args)


def test_recovery_rejects_a_merge_reflog_that_predates_intent(tmp_path, monkeypatch):
    import hashlib
    import json

    args = _integration_args(tmp_path)
    service.integrate_candidate(**args)
    project = args["project_root"]
    path = service._integration_intent_path(project, args["run_id"])
    intent = json.loads(path.read_text(encoding="utf-8"))
    prior_reflog = service._main_reflog_path(project).read_bytes()
    intent.update(mainReflogOffset=len(prior_reflog),
                  mainReflogPrefixDigest=hashlib.sha256(prior_reflog).hexdigest())
    path.write_text(json.dumps(intent), encoding="utf-8")
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("ancestor alone cannot merge"))
    with pytest.raises(service.CandidateIntegrationError, match="stale_main"):
        service.integrate_candidate(**args)


def test_intent_persistence_failure_prevents_irreversible_merge(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    def unavailable(*a, **kw):
        raise OSError("intent storage unavailable")
    monkeypatch.setattr(service, "_write_json_atomic", unavailable)
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("no durable intent means no merge"))
    with pytest.raises(service.CandidateIntegrationError, match="intent storage unavailable"):
        service.integrate_candidate(**args)
    assert _git(args["project_root"], "rev-parse", "HEAD").stdout.strip() == args["expected_head"]


def test_guard_exit_failure_after_merge_recovers_the_completed_fact(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)

    @contextmanager
    def failing_exit():
        yield
        raise RuntimeError("guard finalization unavailable")

    with pytest.raises(service.CandidateIntegrationError, match="guard finalization unavailable"):
        service.integrate_candidate(**args, admission_guard=failing_exit)
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", lambda *a, **kw: pytest.fail("completed merge must not repeat"))
    result = service.integrate_candidate(**args, admission_guard=lambda: pytest.fail("must not readmit"))
    assert result["commitSha"] == args["expected_candidate_commit"]


def test_failed_merge_can_retry_while_frozen_main_is_unchanged(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    merge = service.task_closeout.merge_ff_only
    calls = []
    def fail_once(*a, **kw):
        calls.append(kw["target_sha"])
        if len(calls) == 1:
            raise RuntimeError("transient merge failure")
        return merge(*a, **kw)
    monkeypatch.setattr(service.task_closeout, "merge_ff_only", fail_once)
    with pytest.raises(service.CandidateIntegrationError, match="transient merge failure"):
        service.integrate_candidate(**args)
    result = service.integrate_candidate(**args)
    assert calls == [args["expected_candidate_commit"]] * 2
    assert result["commitSha"] == args["expected_candidate_commit"]


def test_public_recovery_only_reconstructs_a_proven_completed_fact(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    assert service.recover_candidate_integration(**args) is None
    service.integrate_candidate(**args)
    project = args["project_root"]
    (project / "user-notes.txt").write_text("ongoing user work\n", encoding="utf-8")
    reflog_before = service._main_reflog_path(project).read_bytes()
    monkeypatch.setattr(service, "_merge_validated_candidate", lambda *a, **kw: pytest.fail("recovery cannot merge or claim"))
    result = service.recover_candidate_integration(**args)
    assert result["commitSha"] == args["expected_candidate_commit"]
    assert result["governanceCleanup"]["recovered"] is True
    assert service._main_reflog_path(project).read_bytes() == reflog_before
    assert (project / "user-notes.txt").read_text(encoding="utf-8") == "ongoing user work\n"


def _install_governance_registry(args, monkeypatch):
    """Exercise the production release/completion seams against isolated state."""
    registry = {
        "claims": [
            {"id": "development-test", "agentId": "test-owner", "status": "active", "laneId": "development"},
            {"id": "integration-test", "agentId": "test-owner", "status": "active",
             "laneId": "integration", "scopes": ["integration/main"]},
            {"id": "foreign-claim", "agentId": "another-owner", "status": "active", "laneId": "development"},
        ],
        "agents": [
            {"id": "test-owner", "state": "active", "branch": "codex/supervised-candidate",
             "worktree": str(args["candidate_root"])},
            {"id": "another-owner", "state": "active", "branch": "codex/unrelated"},
        ],
    }
    calls = []
    def coordination(context, *argv):
        assert context.main_root == args["project_root"]
        assert context.task_root == args["candidate_root"]
        assert context.branch == "codex/supervised-candidate"
        calls.append(argv)
        if argv == ("status",):
            return deepcopy(registry)
        if argv[0] == "release":
            claim = next(item for item in registry["claims"] if item["id"] == argv[argv.index("--claim-id") + 1])
            claim["status"] = argv[argv.index("--status") + 1]
        elif argv[0] == "complete":
            owner = argv[argv.index("--agent-id") + 1]
            next(item for item in registry["agents"] if item["id"] == owner)["state"] = "completed"
            # The real registry completes all live owned claims. Its shared caller
            # must prevent this command while an unrelated owned claim remains.
            for claim in registry["claims"]:
                if claim["agentId"] == owner and claim["status"] in {"active", "ready", "yielded"}:
                    claim["status"] = "completed"
        else:
            pytest.fail(f"unexpected coordination mutation: {argv}")
        return {}
    monkeypatch.setattr(service.task_closeout, "_coordination_call", coordination)
    monkeypatch.setattr(service.task_closeout, "release_claim", _real_release_claim)
    monkeypatch.setattr(service.task_closeout, "complete_agent", _real_complete_agent)
    return registry, calls


def _lose_receipt_and_leave_recorded_claims(args, monkeypatch):
    @contextmanager
    def fail_after_merge():
        yield
        raise RuntimeError("merge receipt unavailable")

    def unavailable(*a, **kw):
        raise RuntimeError("claim release temporarily unavailable")

    with monkeypatch.context() as unavailable_claims:
        unavailable_claims.setattr(service.task_closeout, "release_claim", unavailable)
        with pytest.raises(service.CandidateIntegrationError, match="merge receipt unavailable"):
            service.integrate_candidate(**args, admission_guard=fail_after_merge)
    assert _git(args["project_root"], "rev-parse", "HEAD").stdout.strip() == args["expected_candidate_commit"]


def test_finish_releases_both_original_claims_after_lost_merge_receipt_and_is_idempotent(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    registry, calls = _install_governance_registry(args, monkeypatch)
    _lose_receipt_and_leave_recorded_claims(args, monkeypatch)
    calls.clear()
    assert service.recover_candidate_integration(**args)["governanceCleanup"]["status"] == "pending"
    assert calls == []  # Fact recovery keeps claims read-only.

    cleanup = service.finish_candidate_integration_governance(**args)
    assert cleanup == {"status": "completed", "errors": []}
    claims = {item["id"]: item for item in registry["claims"]}
    assert claims["development-test"]["status"] == claims["integration-test"]["status"] == "completed"
    assert claims["foreign-claim"]["status"] == "active"
    assert registry["agents"][0]["state"] == "completed"
    assert registry["agents"][1]["state"] == "active"
    assert [call[2] for call in calls if call[0] == "release"] == ["integration-test", "development-test"]

    # Even reusing the recorded agent identity later must not let retry finish
    # the new owner's work or issue a second completion command.
    registry["agents"][0].update(state="active", branch="codex/new-task")
    registry["claims"].append({"id": "new-task", "agentId": "test-owner", "status": "active"})
    calls.clear()
    assert service.finish_candidate_integration_governance(**args) == cleanup
    assert calls == []
    assert registry["claims"][-1]["status"] == "active"
    assert registry["agents"][0]["state"] == "active"
    assert service.recover_candidate_integration(**args)["governanceCleanup"]["status"] == "completed"


def test_finish_preserves_unrelated_owned_claim_and_persists_pending_until_retry(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    registry, calls = _install_governance_registry(args, monkeypatch)
    _lose_receipt_and_leave_recorded_claims(args, monkeypatch)
    other = {"id": "other-owned-claim", "agentId": "test-owner", "status": "active"}
    registry["claims"].append(other)
    with pytest.raises(service.CandidateIntegrationError, match="governance_cleanup_pending.*agent_has_other_active_claims"):
        service.finish_candidate_integration_governance(**args)
    assert other["status"] == "active"
    assert not any(call[0] == "complete" for call in calls)
    recovered = service.recover_candidate_integration(**args)
    assert recovered["governanceCleanup"]["status"] == "pending"
    assert recovered["governanceCleanup"]["errors"]

    other["status"] = "released"  # The unrelated owner resolves its own work.
    calls.clear()
    assert service.finish_candidate_integration_governance(**args)["status"] == "completed"
    assert not any(call[0] == "release" for call in calls)  # Original claims were already released.
    assert other["status"] == "released"


@pytest.mark.parametrize("claim_id", ["integration-test", "development-test"])
def test_finish_refuses_reassigned_recorded_claim_without_any_release(tmp_path, monkeypatch, claim_id):
    args = _integration_args(tmp_path)
    registry, calls = _install_governance_registry(args, monkeypatch)
    _lose_receipt_and_leave_recorded_claims(args, monkeypatch)
    next(item for item in registry["claims"] if item["id"] == claim_id)["agentId"] = "another-owner"
    calls.clear()
    with pytest.raises(service.CandidateIntegrationError, match="governance_binding_changed"):
        service.finish_candidate_integration_governance(**args)
    assert calls == [("status",)]
    assert all(item["status"] == "active" for item in registry["claims"])


def test_finish_requires_proven_integration_before_any_governance_mutation(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    monkeypatch.setattr(service.task_closeout, "_coordination_call", lambda *a: pytest.fail("unproven integration cannot mutate claims"))
    with pytest.raises(service.CandidateIntegrationError, match="integration_not_proven"):
        service.finish_candidate_integration_governance(**args)


@pytest.mark.parametrize("changed_identity", ["lease_scope", "agent_branch", "agent_worktree"])
def test_finish_rejects_recorded_resource_scope_or_agent_task_drift(tmp_path, monkeypatch, changed_identity):
    args = _integration_args(tmp_path)
    registry, calls = _install_governance_registry(args, monkeypatch)
    _lose_receipt_and_leave_recorded_claims(args, monkeypatch)
    if changed_identity == "lease_scope":
        registry["claims"][1]["scopes"] = ["integration/other"]
    elif changed_identity == "agent_branch":
        registry["agents"][0]["branch"] = "codex/new-owner-task"
    else:
        registry["agents"][0]["worktree"] = str(tmp_path / "another-task")
    calls.clear()
    with pytest.raises(service.CandidateIntegrationError, match="governance_binding_changed"):
        service.finish_candidate_integration_governance(**args)
    assert calls == [("status",)]
    assert all(item["status"] == "active" for item in registry["claims"])


def test_finish_retries_failed_lease_release_without_releasing_development_twice(tmp_path, monkeypatch):
    args = _integration_args(tmp_path)
    registry, calls = _install_governance_registry(args, monkeypatch)
    def failed_lease(context, claim_id, **kwargs):
        if claim_id == "integration-test":
            raise RuntimeError("lease release unavailable")
        return _real_release_claim(context, claim_id, **kwargs)
    with monkeypatch.context() as unavailable_lease:
        unavailable_lease.setattr(service.task_closeout, "release_claim", failed_lease)
        result = service.integrate_candidate(**args)
    assert result["governanceCleanup"]["status"] == "pending"
    assert registry["claims"][0]["status"] == "completed"
    assert registry["claims"][1]["status"] == "active"
    calls.clear()
    assert service.finish_candidate_integration_governance(**args)["status"] == "completed"
    assert [call[2] for call in calls if call[0] == "release"] == ["integration-test"]
    assert registry["claims"][2]["status"] == "active"
