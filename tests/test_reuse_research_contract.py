from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import github_project_library_service as library
from core.infrastructure.git_process import run_git
from scripts import reuse_research_contract as contract
from scripts.local_quality_gate import git_hook_isolated_environment


def git(root: Path, *args: str) -> str:
    completed = run_git(
        [*args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=git_hook_isolated_environment(),
    )
    return completed.stdout.strip()


def seed_task_repo(root: Path) -> None:
    git(root, "init")
    git(root, "config", "user.email", "reuse@example.invalid")
    git(root, "config", "user.name", "Reuse Research")
    (root / "core").mkdir()
    (root / "core" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "seed")
    git(root, "switch", "-c", "codex/reuse-task")


def seed_candidate(project_root: Path, *, license_id: str = "MIT") -> dict[str, str]:
    library_root = library.github_project_library_root(project_root=project_root)
    repo = library_root / "repos" / "acme__widget"
    repo.mkdir(parents=True)
    git(repo, "init")
    git(repo, "config", "user.email", "candidate@example.invalid")
    git(repo, "config", "user.name", "Candidate")
    (repo / "README.md").write_text("# Widget\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "candidate")
    head = git(repo, "rev-parse", "HEAD")
    registry = {
        "schemaVersion": 1,
        "updatedAt": "2026-08-26T00:00:00Z",
        "projects": [
            {
                "projectId": "acme__widget",
                "name": "widget",
                "fullName": "acme/widget",
                "description": "A mature widget implementation.",
                "githubUrl": "https://github.com/acme/widget",
                "defaultBranch": "main",
                "headSha": head,
                "license": license_id,
                "language": "Python",
                "stars": 10,
                "hasSubmodules": False,
                "status": "ready",
                "clonedAt": "2026-08-26T00:00:00Z",
                "updatedAt": "2026-08-26T00:00:00Z",
                "error": "",
            }
        ],
    }
    library._write_registry(library_root, registry)
    library._write_index(library_root, registry)
    return {"head": head, "repo": str(repo)}


def record_payload(root: Path) -> dict[str, object]:
    return contract.record_evidence(
        root,
        feature="Evidence-backed feature development",
        decision="ADAPT",
        local_reuse_decision="ADAPT",
        local_owner_paths=["core/feature.py"],
        candidate_ids=["acme__widget"],
        borrowed_slices=["Bind every external claim to a fixed repository SHA."],
        rejected_alternatives=["Copying the whole repository would violate ownership boundaries."],
        reason="The candidate lowers design risk without becoming a product dependency.",
        implementation_boundary="Only the task evidence contract changes.",
        verification_strategy="Run contract and closeout tests.",
        risk_notes=[],
        source_refs=["acme__widget:README.md#overview"],
        project_root=root,
    )


def test_implementation_changes_require_reuse_research_but_docs_only_do_not() -> None:
    assert contract.reuse_research_required(["core/feature.py"]) is True
    assert contract.reuse_research_required(["web/src/Feature.tsx"]) is True
    assert contract.reuse_research_required(["docs/guide.md", "tests/fixture.json"]) is False


def test_record_evidence_hydrates_candidate_metadata_and_loads_snapshot(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    candidate = seed_candidate(tmp_path)

    payload = record_payload(tmp_path)
    loaded = contract.load_and_validate_evidence(
        tmp_path,
        task_id="reuse-task",
        branch="codex/reuse-task",
        project_root=tmp_path,
    )

    assert payload == loaded
    assert payload["candidates"] == [
        {
            "projectId": "acme__widget",
            "fullName": "acme/widget",
            "githubUrl": "https://github.com/acme/widget",
            "localPath": "repos/acme__widget",
            "headSha": candidate["head"],
            "license": "MIT",
            "status": "ready",
        }
    ]
    assert payload["sourceRefs"] == [
        {
            "projectId": "acme__widget",
            "headSha": candidate["head"],
            "path": "README.md",
            "symbol": "overview",
            "blobSha": git(Path(candidate["repo"]), "rev-parse", f"{candidate['head']}:README.md"),
        }
    ]
    assert Path(contract.evidence_path(tmp_path, "reuse-task")).is_file()


def test_local_only_evidence_skips_external_registry_and_validates_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_task_repo(tmp_path)
    monkeypatch.setattr(
        contract,
        "_read_registry",
        lambda *_args, **_kwargs: pytest.fail("LOCAL_ONLY must not read the external registry"),
    )

    payload = contract.record_evidence(
        tmp_path,
        feature="Located closeout retry fix",
        research_mode="LOCAL_ONLY",
        decision="BUILD_IN_HOUSE",
        local_reuse_decision="ADAPT",
        local_owner_paths=["core/feature.py"],
        candidate_ids=[],
        borrowed_slices=[],
        rejected_alternatives=[],
        reason="The defect and owning surface are already confirmed locally.",
        implementation_boundary="Only the bounded retry behavior changes.",
        verification_strategy="Run the focused closeout contract tests.",
        risk_notes=[],
        source_refs=[],
        project_root=tmp_path,
    )

    assert payload["researchMode"] == "LOCAL_ONLY"
    assert payload["candidates"] == []
    assert payload["sourceRefs"] == []
    assert contract.load_and_validate_evidence(
        tmp_path,
        task_id="reuse-task",
        branch="codex/reuse-task",
        project_root=tmp_path,
    ) == payload
    assert contract.validate_manifest_snapshot(payload, tmp_path) == payload


@pytest.fixture
def launcher_reuse_tool(tmp_path, monkeypatch):
    from core.web.services import agent_directory_service
    from core.web.services.local_assistant import consent
    from tools.Key_Tools import create_key_tools

    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    monkeypatch.delenv("GIT_COMMON_DIR", raising=False)
    seed_task_repo(tmp_path)
    git(tmp_path, "branch", "-M", "main")
    (tmp_path / ".git/info/exclude").write_text(".worktrees/\n", encoding="utf-8")
    slug = "assistant-eat-fixture"
    branch = "codex/" + slug
    workspace = tmp_path / ".worktrees" / slug
    git(tmp_path, "worktree", "add", "-b", branch, str(workspace), "main")
    runtime = {"runtimeToolSource": "launcher_assistant_task:workspace_write"}
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda *, bound_only: runtime if bound_only else {})
    monkeypatch.setattr(consent, "_task_runtime", lambda runtime: {
        "taskId": "eat-fixture", "workspace": workspace, "profile": "workspace_write",
    })
    tool = next(tool for tool in create_key_tools() if tool.name == "record_local_reuse_evidence_tool")
    args = {"feature": "Small example fix", "local_reuse_decision": "ADAPT",
            "local_owner_paths": ["core/feature.py"], "reason": "Confirmed existing owner.",
            "implementation_boundary": "Change only example behavior.", "verification_strategy": "Run the focused test."}
    return tool, args, workspace, slug, branch, runtime


def test_launcher_tool_records_existing_closeout_evidence(launcher_reuse_tool, tmp_path):
    tool, args, workspace, slug, branch, _ = launcher_reuse_tool

    result = json.loads(tool.invoke(args))

    assert result == {"ok": True, "taskId": "eat-fixture", "branch": branch, "researchMode": "LOCAL_ONLY"}
    evidence = contract.load_and_validate_evidence(workspace, task_id=slug, branch=branch)
    assert evidence["localOwnerPaths"] == args["local_owner_paths"]
    assert evidence["verificationStrategy"] == args["verification_strategy"]
    assert not git(workspace, "status", "--porcelain")
    assert not git(tmp_path, "status", "--porcelain")


def test_launcher_tool_denies_wrong_branch_or_inactive_session(launcher_reuse_tool):
    from core.web.services.local_assistant.consent import LocalTaskScopeError

    tool, args, workspace, slug, branch, runtime = launcher_reuse_tool
    git(workspace, "branch", "-m", "codex/another-task")
    assert not json.loads(tool.invoke(args))["ok"]
    assert not contract.evidence_path(workspace, slug).exists()
    assert not contract.evidence_path(workspace, "another-task").exists()
    runtime.clear()
    with pytest.raises(LocalTaskScopeError):
        tool.invoke(args)


def test_launcher_tool_rejects_redirected_cache_and_unsafe_arguments(launcher_reuse_tool, tmp_path):
    from pydantic import ValidationError

    tool, args, workspace, slug, _, _ = launcher_reuse_tool
    with pytest.raises(ValidationError):
        tool.invoke({**args, "project_root": str(tmp_path)})
    for path in ("../core/feature.py", ".git"):
        assert not json.loads(tool.invoke({**args, "local_owner_paths": [path]}))["ok"]
    assert not contract.evidence_path(workspace, slug).exists()
    outside = tmp_path.parent / (tmp_path.name + "-cache-target")
    outside.mkdir()
    cache = tmp_path / ".git/vibelution-cache"
    try:
        cache.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")
    assert not json.loads(tool.invoke(args))["ok"]
    assert not list(outside.iterdir())
    cache.unlink()
    path = contract.evidence_path(workspace, slug)
    path.parent.mkdir(parents=True)
    lock = path.with_name(path.name + ".lock")
    lock.symlink_to(outside / "lock-target")
    assert json.loads(tool.invoke(args))["ok"]
    assert not list(outside.iterdir())


def test_local_only_rejects_external_candidate_fields(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)

    with pytest.raises(contract.ReuseResearchEvidenceError, match="must not include"):
        contract.record_evidence(
            tmp_path,
            feature="Located closeout retry fix",
            research_mode="LOCAL_ONLY",
            decision="BUILD_IN_HOUSE",
            local_reuse_decision="ADAPT",
            local_owner_paths=["core/feature.py"],
            candidate_ids=["acme__widget"],
            borrowed_slices=[],
            rejected_alternatives=[],
            reason="The defect and owning surface are already confirmed locally.",
            implementation_boundary="Only the bounded retry behavior changes.",
            verification_strategy="Run the focused closeout contract tests.",
            risk_notes=[],
            source_refs=[],
            project_root=tmp_path,
        )


def test_record_evidence_requires_source_ref_bound_to_candidate(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)

    with pytest.raises(contract.ReuseResearchEvidenceError, match="sourceRefs"):
        contract.record_evidence(
            tmp_path,
            feature="Evidence-backed feature development",
            decision="ADAPT",
            local_reuse_decision="ADAPT",
            local_owner_paths=["core/feature.py"],
            candidate_ids=["acme__widget"],
            borrowed_slices=["Use a fixed source location."],
            rejected_alternatives=["Do not copy the whole repository."],
            reason="The candidate lowers design risk.",
            implementation_boundary="Only the evidence contract changes.",
            verification_strategy="Run contract tests.",
            risk_notes=[],
            source_refs=[],
            project_root=tmp_path,
        )


def test_record_evidence_rejects_source_ref_for_unselected_candidate(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)

    with pytest.raises(contract.ReuseResearchEvidenceError, match="selected candidate"):
        contract.record_evidence(
            tmp_path,
            feature="Evidence-backed feature development",
            decision="ADAPT",
            local_reuse_decision="ADAPT",
            local_owner_paths=["core/feature.py"],
            candidate_ids=["acme__widget"],
            borrowed_slices=["Use a fixed source location."],
            rejected_alternatives=["Do not copy the whole repository."],
            reason="The candidate lowers design risk.",
            implementation_boundary="Only the evidence contract changes.",
            verification_strategy="Run contract tests.",
            risk_notes=[],
            source_refs=["other__project:README.md#overview"],
            project_root=tmp_path,
        )


def test_record_evidence_rejects_missing_source_ref_file(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)

    with pytest.raises(contract.ReuseResearchEvidenceError, match="file blob"):
        contract.record_evidence(
            tmp_path,
            feature="Evidence-backed feature development",
            decision="ADAPT",
            local_reuse_decision="ADAPT",
            local_owner_paths=["core/feature.py"],
            candidate_ids=["acme__widget"],
            borrowed_slices=["Use a fixed source location."],
            rejected_alternatives=["Do not copy the whole repository."],
            reason="The candidate lowers design risk.",
            implementation_boundary="Only the evidence contract changes.",
            verification_strategy="Run contract tests.",
            risk_notes=[],
            source_refs=["acme__widget:missing.py#missing_symbol"],
            project_root=tmp_path,
        )


def test_record_evidence_rejects_source_ref_path_escape(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)

    with pytest.raises(contract.ReuseResearchEvidenceError, match="source reference path"):
        contract.record_evidence(
            tmp_path,
            feature="Evidence-backed feature development",
            decision="ADAPT",
            local_reuse_decision="ADAPT",
            local_owner_paths=["core/feature.py"],
            candidate_ids=["acme__widget"],
            borrowed_slices=["Use a fixed source location."],
            rejected_alternatives=["Do not copy the whole repository."],
            reason="The candidate lowers design risk.",
            implementation_boundary="Only the evidence contract changes.",
            verification_strategy="Run contract tests.",
            risk_notes=[],
            source_refs=["acme__widget:../README.md"],
            project_root=tmp_path,
        )


def test_adapt_rejects_candidate_with_unverified_license(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path, license_id="NOASSERTION")

    with pytest.raises(contract.ReuseResearchEvidenceError, match="license"):
        record_payload(tmp_path)


def test_closeout_validation_rejects_candidate_head_drift(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    candidate = seed_candidate(tmp_path)
    record_payload(tmp_path)
    repo = Path(candidate["repo"])
    (repo / "README.md").write_text("# Changed\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "move head")

    with pytest.raises(contract.ReuseResearchEvidenceError, match="HEAD"):
        contract.load_and_validate_evidence(
            tmp_path,
            task_id="reuse-task",
            branch="codex/reuse-task",
            project_root=tmp_path,
        )


def test_manifest_snapshot_validation_rejects_tampered_candidate_sha(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)
    payload = record_payload(tmp_path)
    tampered = json.loads(json.dumps(payload))
    tampered["candidates"][0]["headSha"] = "0" * 40

    with pytest.raises(contract.ReuseResearchEvidenceError, match="commit"):
        contract.validate_manifest_snapshot(tampered, tmp_path, project_root=tmp_path)


def test_manifest_snapshot_validation_rejects_tampered_source_blob(tmp_path: Path) -> None:
    seed_task_repo(tmp_path)
    seed_candidate(tmp_path)
    payload = record_payload(tmp_path)
    tampered = json.loads(json.dumps(payload))
    tampered["sourceRefs"][0]["blobSha"] = "0" * 40

    with pytest.raises(contract.ReuseResearchEvidenceError, match="blob"):
        contract.validate_manifest_snapshot(tampered, tmp_path, project_root=tmp_path)
