from __future__ import annotations

from core.web.services import github_project_library_service as library
from core.web.services import unified_knowledge_search_service as unified


def test_unified_github_projection_preserves_ranked_search_score(tmp_path, monkeypatch):
    root = library.github_project_library_root(project_root=tmp_path)
    registry = {
        "schemaVersion": 1,
        "updatedAt": "2026-08-26T00:00:00Z",
        "projects": [
            {
                "projectId": "mem0ai__mem0",
                "name": "mem0",
                "fullName": "mem0ai/mem0",
                "description": "Universal memory layer for AI Agents",
                "githubUrl": "https://github.com/mem0ai/mem0",
                "headSha": "a" * 40,
                "license": "Apache-2.0",
                "language": "Python",
                "status": "ready",
            },
            {
                "projectId": "acme__terminal",
                "name": "terminal",
                "fullName": "acme/terminal",
                "description": "ANSI terminal colors",
                "githubUrl": "https://github.com/acme/terminal",
                "headSha": "b" * 40,
                "license": "MIT",
                "language": "Python",
                "status": "ready",
            },
        ],
    }
    library._write_registry(root, registry)
    library._write_index(root, registry)
    repo = root / "repos" / "mem0ai__mem0"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("Hybrid semantic and BM25 memory retrieval.", encoding="utf-8")
    monkeypatch.setattr(library, "PROJECT_ROOT", tmp_path)

    results = unified._github_project_results(query="智能体记忆检索", limit=8)

    assert results
    assert results[0]["title"] == "mem0"
    assert 0 < results[0]["score"] < 1
    assert results[0]["metadata"]["matchedTerms"]
