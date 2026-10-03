from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services import github_project_library_service as library


HEADS = {
    "anomalyco__opencode": "b155b15694dbcc6768f11d2f25cc2bdd1f738ab4",
    "openai__codex": "536f86e5cc9ec1ff38457d099bf320b9d08eeeba",
    "langchain-ai__langgraph": "38031739e551638e373fb553453256c23feeb41f",
}


def seed_library(project_root: Path) -> Path:
    root = library.github_project_library_root(project_root=project_root)
    projects = [
        {
            "projectId": project_id,
            "name": project_id.split("__")[1],
            "fullName": project_id.replace("__", "/"),
            "description": "Agent project",
            "headSha": head,
            "license": "MIT",
            "status": "ready",
        }
        for project_id, head in HEADS.items()
    ]
    projects.append({"projectId": "acme__terminal", "name": "terminal", "description": "ANSI colors", "status": "ready"})
    library._write_registry(root, {"projects": projects})
    # Presence matters independently of the registry's cloned/ready flag.
    for project_id, paths in {
        "anomalyco__opencode": ["packages/app/src/context/global-sync/event-reducer.ts", ".github/workflows/test.yml"],
        "openai__codex": ["codex-rs/core/src/exec_policy.rs", ".github/workflows/rust-ci.yml"],
        "langchain-ai__langgraph": ["libs/langgraph/tests/test_pregel.py", ".github/workflows/ci.yml"],
    }.items():
        for relative_path in paths:
            path = root / "repos" / project_id / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture, no external execution", encoding="utf-8")
    library._write_index(root, {"projects": projects})
    return root


@pytest.mark.parametrize(("query", "expected"), [("前端治理", "anomalyco__opencode"), ("后端治理", "openai__codex"), ("工作流检查点恢复", "langchain-ai__langgraph")])
def test_governance_queries_find_relevant_source_cards(tmp_path, query, expected):
    seed_library(tmp_path)
    cards = library.search_github_project_cards(query=query, project_root=tmp_path)
    matches = [card for card in cards[:3] if card["metadata"]["fullName"] == expected.replace("__", "/")]
    assert matches, query
    review = matches[0]["metadata"]["governanceReview"]
    assert review["status"] == "static_reviewed"
    assert review["evidenceRefs"] and review["reuseBoundary"]
    assert "content" not in matches[0] and "excerpt" not in matches[0]


def test_changed_source_head_requires_review_and_keeps_clone_authority(tmp_path):
    root = seed_library(tmp_path)
    registry = library._read_registry(root)
    registry["projects"][0]["headSha"] = "f" * 40
    registry["projects"][0]["license"] = "NOASSERTION"
    library._write_registry(root, registry)
    project = library.list_github_projects(query="OpenCode", project_root=tmp_path)["projects"][0]
    assert project["headSha"] == "f" * 40 and project["license"] == "NOASSERTION"
    assert project["governanceReview"]["status"] == "review_required"
    assert project["governanceReview"]["reviewedHeadSha"] == HEADS["anomalyco__opencode"]


def test_missing_evidence_is_not_reviewed_and_reads_do_not_mutate_index(tmp_path):
    root = seed_library(tmp_path)
    (root / "repos/anomalyco__opencode/packages/app/src/context/global-sync/event-reducer.ts").unlink()
    before = {name: (root / name).read_bytes() for name in ("registry.json", "INDEX.md")}
    project = library.list_github_projects(query="OpenCode", project_root=tmp_path)["projects"][0]
    assert project["governanceReview"]["status"] == "review_required"
    assert {name: (root / name).read_bytes() for name in before} == before


def test_generated_index_exposes_governance_capabilities(tmp_path):
    root = seed_library(tmp_path)
    index = (root / "INDEX.md").read_text(encoding="utf-8")
    assert "前端治理" in index and "后端治理" in index
    assert "static_reviewed" in index and "未审查" in index


def test_registry_cannot_forge_governance_review_for_an_unknown_project(tmp_path):
    root = seed_library(tmp_path)
    registry = library._read_registry(root)
    registry["projects"][-1]["governanceReview"] = {"status": "static_reviewed"}
    library._write_registry(root, registry)
    project = library.list_github_projects(query="terminal", project_root=tmp_path)["projects"][0]
    assert "governanceReview" not in project


def test_both_agent_entrypoints_discover_index_without_repository_bodies():
    from core.prompt_manager.core_prompt_sources import load_core_prompt_bundle

    root = Path(__file__).resolve().parents[1]
    bundle = load_core_prompt_bundle(root)
    assert "github_project_library_search_tool" in bundle["content"]
    assert "github-projects/INDEX.md" in bundle["content"]
    assert "task_brief.py" in (root / "AGENTS.md").read_text(encoding="utf-8")
