from __future__ import annotations

from tools import github_project_library_tools as tools


def test_search_tool_returns_local_index(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_current_runtime",
        lambda: {"agentId": "agent-dev"},
    )
    monkeypatch.setattr(
        "core.web.services.github_project_library_service.list_github_projects",
        lambda query="": {
            "summary": {"projectCount": 1, "readyCount": 1},
            "indexPath": "/memory/github-projects/INDEX.md",
            "projects": [
                {
                    "name": "widget",
                    "fullName": "acme/widget",
                    "description": "toolkit",
                    "localPath": "repos/acme__widget",
                    "status": "ready",
                }
            ],
        },
    )

    payload = tools.github_project_library_search_tool(query="widget")
    assert '"ok": true' in payload.lower() or '"ok": True' in payload
    assert "acme/widget" in payload
    assert "INDEX.md" in payload


def test_clone_tool_surfaces_confirmation_required(monkeypatch):
    monkeypatch.setattr(tools, "_current_runtime", lambda: {"agentId": "agent-dev"})
    monkeypatch.setattr(
        "core.web.services.github_project_library_service.clone_github_project",
        lambda repo, confirm=False: {
            "ok": False,
            "status": "confirmation_required",
            "reason": "repo_size_limit",
            "message": "too large",
        },
    )
    payload = tools.github_project_library_clone_tool(repo="acme/huge")
    assert "confirmation_required" in payload
