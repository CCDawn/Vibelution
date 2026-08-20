from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.web.services import github_project_library_service as library


def _metadata(owner: str = "acme", repo: str = "widget", **overrides):
    payload = {
        "projectId": f"{owner}__{repo}",
        "name": repo,
        "fullName": f"{owner}/{repo}",
        "description": "A tiny widget toolkit for dense workbenches.",
        "githubUrl": f"https://github.com/{owner}/{repo}",
        "cloneUrl": f"https://github.com/{owner}/{repo}.git",
        "defaultBranch": "main",
        "license": "MIT",
        "language": "Python",
        "stars": 12,
        "sizeKb": 80,
        "private": False,
        "visibility": "public",
    }
    payload.update(overrides)
    return payload


def _fake_clone(dest, metadata):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text(f"# {metadata['name']}\n", encoding="utf-8")
    git_dir = dest / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def test_parse_github_spec_accepts_url_and_owner_repo():
    assert library.parse_github_spec("https://github.com/acme/widget.git") == ("acme", "widget")
    assert library.parse_github_spec("acme/widget") == ("acme", "widget")
    with pytest.raises(library.GithubProjectLibraryError):
        library.parse_github_spec("not a repo")


def test_clone_writes_registry_and_generated_index(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        calls.append(list(args))
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123def456\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))
    monkeypatch.setattr(library, "run_git", fake_run_git)

    payload = library.clone_github_project("acme/widget", project_root=tmp_path)

    assert payload["status"] == "cloned"
    assert payload["project"]["name"] == "widget"
    assert payload["project"]["description"] == "A tiny widget toolkit for dense workbenches."
    assert payload["project"]["headSha"] == "abc123def456"
    assert payload["project"]["hasSubmodules"] is False
    index_text = (tmp_path / ".docs" / "project-memory" / "github-projects" / "INDEX.md").read_text(encoding="utf-8")
    assert "| widget |" in index_text
    assert "A tiny widget toolkit for dense workbenches." in index_text
    listed = library.list_github_projects(query="workbench", project_root=tmp_path)
    assert listed["summary"]["readyCount"] == 1
    assert listed["projects"][0]["fullName"] == "acme/widget"
    clone_call = next(item for item in calls if item[:1] == ["clone"])
    assert clone_call[:8] == [
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        "main",
        "--no-recurse-submodules",
        "https://github.com/acme/widget.git",
    ]
    assert "浅克隆" in index_text
    assert payload["message"].startswith("已克隆默认主干最新提交")


def test_clone_is_idempotent_when_local_copy_exists(tmp_path, monkeypatch):
    clone_calls = {"count": 0}

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            clone_calls["count"] += 1
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))
    monkeypatch.setattr(library, "run_git", fake_run_git)

    first = library.clone_github_project("https://github.com/acme/widget", project_root=tmp_path)
    second = library.clone_github_project("acme/widget", project_root=tmp_path)

    assert first["status"] == "cloned"
    assert second["status"] == "already_present"
    assert clone_calls["count"] == 1


def test_clone_requires_confirmation_when_library_is_full(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "MAX_PROJECTS", 1)
    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))

    root = tmp_path / ".docs" / "project-memory" / "github-projects"
    library.initialize_github_project_library(project_root=tmp_path)
    registry = {
        "schemaVersion": 1,
        "updatedAt": "",
        "projects": [
            {
                "projectId": "other__repo",
                "name": "repo",
                "fullName": "other/repo",
                "description": "existing",
                "githubUrl": "https://github.com/other/repo",
                "status": "ready",
            }
        ],
    }
    library._write_registry(root, registry)
    library._write_index(root, registry)

    blocked = library.clone_github_project("acme/widget", project_root=tmp_path)
    assert blocked["status"] == "confirmation_required"
    assert blocked["reason"] == "repo_count_limit"

    confirmed_calls = {"clone": 0}

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        dest = root / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            confirmed_calls["clone"] += 1
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "run_git", fake_run_git)
    confirmed = library.clone_github_project("acme/widget", confirm=True, project_root=tmp_path)
    assert confirmed["status"] == "cloned"
    assert confirmed_calls["clone"] == 1


def test_search_cards_are_metadata_only(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "run_git", fake_run_git)
    library.clone_github_project("acme/widget", project_root=tmp_path)
    cards = library.search_github_project_cards(query="widget", project_root=tmp_path)
    assert len(cards) == 1
    assert cards[0]["resultType"] == "github_project_card"
    assert "excerpt" not in cards[0]
    assert "content" not in cards[0]
    assert cards[0]["metadata"]["absolutePath"].endswith("acme__widget")


def test_http_lists_library_and_requires_confirmation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    monkeypatch.setattr(library, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(library, "MAX_PROJECTS", 0)
    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    listed = client.get("/api/memory/github-projects")
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"]["projectCount"] == 0

    blocked = client.post("/api/memory/github-projects", json={"spec": "acme/widget"})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "confirmation_required"


def test_rejects_private_repositories(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library,
        "fetch_github_repo_metadata",
        lambda owner, repo: _metadata(owner, repo, private=True, visibility="private"),
    )
    with pytest.raises(library.GithubProjectLibraryError, match="public"):
        library.clone_github_project("acme/secret", project_root=tmp_path)


def test_clone_follows_github_default_branch(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        calls.append(list(args))
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            _fake_clone(dest, _metadata(defaultBranch="dev"))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="devtip\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        library,
        "fetch_github_repo_metadata",
        lambda owner, repo: _metadata(owner, repo, defaultBranch="dev"),
    )
    monkeypatch.setattr(library, "run_git", fake_run_git)

    payload = library.clone_github_project("acme/widget", project_root=tmp_path)
    clone_call = next(item for item in calls if item[:1] == ["clone"])
    assert clone_call[5] == "dev"
    assert payload["project"]["defaultBranch"] == "dev"
    assert payload["project"]["headSha"] == "devtip"


def test_fetch_fast_forwards_default_branch_tip(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        calls.append(list(args))
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if args[:1] == ["clone"]:
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[:1] == ["fetch"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["merge", "--ff-only", "FETCH_HEAD"]:
            return SimpleNamespace(returncode=0, stdout="Already up to date.\n", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="newsha\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))
    monkeypatch.setattr(library, "run_git", fake_run_git)

    library.clone_github_project("acme/widget", project_root=tmp_path)
    updated = library.fetch_github_project("acme/widget", project_root=tmp_path)

    assert updated["status"] == "updated"
    assert updated["project"]["headSha"] == "newsha"
    assert ["fetch", "--depth", "1", "--no-recurse-submodules", "origin", "main"] in calls
    assert ["merge", "--ff-only", "FETCH_HEAD"] in calls
