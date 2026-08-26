from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.web.services import github_project_library_service as library
from scripts import reuse_research_contract as contract


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
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
    assert Path(contract.evidence_path(tmp_path, "reuse-task")).is_file()


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
