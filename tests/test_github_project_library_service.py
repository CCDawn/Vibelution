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


def _is_clone(args) -> bool:
    return "clone" in args


def _is_fetch(args) -> bool:
    return "fetch" in args


def _fake_clone(dest, metadata):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text(f"# {metadata['name']}\n", encoding="utf-8")
    git_dir = dest / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def _seed_search_projects(tmp_path):
    root = library.github_project_library_root(project_root=tmp_path)
    projects = [
        {
            **_metadata("mem0ai", "mem0"),
            "description": "Universal memory layer for AI Agents",
            "headSha": "a" * 40,
            "status": "ready",
        },
        {
            **_metadata("langgenius", "dify"),
            "description": "Build Agentic workflows and RAG pipelines",
            "headSha": "b" * 40,
            "status": "ready",
        },
        {
            **_metadata("microsoft", "markitdown"),
            "description": "Convert files and office documents to Markdown",
            "headSha": "c" * 40,
            "status": "ready",
        },
        {
            **_metadata("acme", "unrelated"),
            "description": "A tiny terminal color utility",
            "headSha": "d" * 40,
            "status": "ready",
        },
    ]
    registry = {"schemaVersion": 1, "updatedAt": "2026-08-26T00:00:00Z", "projects": projects}
    library._write_registry(root, registry)
    library._write_index(root, registry)
    readmes = {
        "mem0ai__mem0": "Hybrid semantic and BM25 retrieval with metadata filters and reranking.",
        "langgenius__dify": "Workflow orchestration with knowledge retrieval and weighted ranking.",
        "microsoft__markitdown": "Document parsing and converter plugins for PDF DOCX and PPTX.",
        "acme__unrelated": "ANSI colors for command line output.",
    }
    for project_id, content in readmes.items():
        repo = root / "repos" / project_id
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "README.md").write_text(content, encoding="utf-8")
    return root


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
        if _is_clone(args):
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
    clone_call = next(item for item in calls if _is_clone(item))
    assert clone_call[:10] == [
        "-c",
        "core.longpaths=true",
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
        if _is_clone(args):
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


def test_clone_warns_but_does_not_require_confirmation_when_library_is_large(tmp_path, monkeypatch):
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

    clone_calls = {"count": 0}

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        dest = root / "repos" / "acme__widget"
        if _is_clone(args):
            clone_calls["count"] += 1
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(library, "run_git", fake_run_git)
    cloned = library.clone_github_project("acme/widget", project_root=tmp_path)
    assert cloned["status"] == "cloned"
    assert cloned["warnings"] == ["project_count_above_soft_threshold"]
    assert clone_calls["count"] == 1


@pytest.mark.parametrize("license_id", ["", "NOASSERTION"])
def test_clone_requires_confirmation_when_license_is_unverified(tmp_path, monkeypatch, license_id):
    monkeypatch.setattr(
        library,
        "fetch_github_repo_metadata",
        lambda owner, repo: _metadata(owner, repo, license=license_id),
    )

    blocked = library.clone_github_project("acme/widget", project_root=tmp_path)

    assert blocked["status"] == "confirmation_required"
    assert blocked["reason"] == "license_unverified"


def test_clone_requires_confirmation_when_repository_is_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(
        library,
        "fetch_github_repo_metadata",
        lambda owner, repo: _metadata(owner, repo, sizeKb=library.MAX_REPO_SIZE_KB + 1),
    )

    blocked = library.clone_github_project("acme/widget", project_root=tmp_path)

    assert blocked["status"] == "confirmation_required"
    assert blocked["reason"] == "repo_size_limit"


def test_search_cards_are_metadata_only(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "fetch_github_repo_metadata", lambda owner, repo: _metadata(owner, repo))

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if _is_clone(args):
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


def test_list_is_pure_read_when_library_is_missing(tmp_path):
    root = library.github_project_library_root(project_root=tmp_path)

    payload = library.list_github_projects(query="agent memory", project_root=tmp_path)

    assert payload["projects"] == []
    assert payload["summary"]["projectCount"] == 0
    assert root.exists() is False


def test_list_query_never_rewrites_registry_or_index(tmp_path, monkeypatch):
    root = _seed_search_projects(tmp_path)
    registry_path = root / library.REGISTRY_NAME
    index_path = root / library.INDEX_NAME
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (registry_path, index_path)
    }

    monkeypatch.setattr(
        library,
        "_write_registry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search must not write registry")),
    )
    monkeypatch.setattr(
        library,
        "_write_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search must not write index")),
    )

    payload = library.list_github_projects(query="workflow orchestration", project_root=tmp_path)

    assert payload["projects"][0]["projectId"] == "langgenius__dify"
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (registry_path, index_path)
    } == before


@pytest.mark.parametrize(
    ("query", "expected_project_id"),
    [
        ("agent memory", "mem0ai__mem0"),
        ("workflow orchestration", "langgenius__dify"),
        ("document parsing", "microsoft__markitdown"),
        ("知识库检索", "langgenius__dify"),
        ("文档解析", "microsoft__markitdown"),
    ],
)
def test_search_ranks_multiword_and_chinese_capability_queries(tmp_path, query, expected_project_id):
    _seed_search_projects(tmp_path)

    payload = library.list_github_projects(query=query, project_root=tmp_path)

    assert payload["projects"], query
    first = payload["projects"][0]
    assert first["projectId"] == expected_project_id
    assert 0 < first["searchScore"] <= 1
    assert first["matchedTerms"]
    assert first["matchReason"] in {
        "exact_name",
        "metadata_phrase",
        "metadata_terms",
        "metadata_and_readme_terms",
        "readme_terms",
    }


def test_search_cards_use_explainable_nonconstant_relevance_scores(tmp_path):
    _seed_search_projects(tmp_path)

    cards = library.search_github_project_cards(query="agent memory workflow", project_root=tmp_path)

    assert len(cards) >= 2
    assert cards[0]["score"] > cards[1]["score"]
    assert cards[0]["score"] != 1.0
    assert cards[0]["matchReason"] != "local_github_project_index"
    assert cards[0]["metadata"]["matchedTerms"]


def test_http_lists_library_and_requires_confirmation_for_unverified_license(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    monkeypatch.setattr(library, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        library,
        "fetch_github_repo_metadata",
        lambda owner, repo: _metadata(owner, repo, license="NOASSERTION"),
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>\n", encoding="utf-8")
    monkeypatch.setattr(
        "core.web.app.build_serving_metadata",
        lambda root: {
            "schemaVersion": 1,
            "apiContractVersion": "v1",
            "frontend": {"buildKey": "test", "release": "test", "dist": str(dist)},
            "backend": {},
        },
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    listed = client.get("/api/memory/github-projects")
    assert listed.status_code == 200, listed.text
    assert listed.json()["summary"]["projectCount"] == 0

    blocked = client.post("/api/memory/github-projects", json={"spec": "acme/widget"})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "confirmation_required"
    assert blocked.json()["reason"] == "license_unverified"


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
        if _is_clone(args):
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
    clone_call = next(item for item in calls if _is_clone(item))
    assert clone_call[7] == "dev"
    assert payload["project"]["defaultBranch"] == "dev"
    assert payload["project"]["headSha"] == "devtip"


def test_fetch_fast_forwards_default_branch_tip(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run_git(args, *, cwd, timeout=15.0, env=None):
        calls.append(list(args))
        dest = tmp_path / ".docs" / "project-memory" / "github-projects" / "repos" / "acme__widget"
        if _is_clone(args):
            _fake_clone(dest, _metadata())
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if _is_fetch(args):
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
    assert ["-c", "core.longpaths=true", "fetch", "--depth", "1", "--no-recurse-submodules", "origin", "main"] in calls
    assert ["merge", "--ff-only", "FETCH_HEAD"] in calls


def test_git_failure_text_prefers_error_lines_over_progress():
    completed = SimpleNamespace(
        stderr=(
            "Cloning into 'repo'...\n"
            "Updating files:  25% (2507/9889)\n"
            "error: unable to create file very/long/path.snap: Filename too long\n"
            "Updating files:  26% (2572/9889)\n"
        ),
        stdout="",
    )
    text = library._git_failure_text(completed, fallback="git clone failed.")
    assert "Filename too long" in text
    assert "Updating files" not in text


def test_remove_clone_dir_deletes_readonly_git_files(tmp_path):
    dest = tmp_path / "stuck-clone"
    git_dir = dest / ".git"
    git_dir.mkdir(parents=True)
    locked = git_dir / "HEAD"
    locked.write_text("ref: refs/heads/main\n", encoding="utf-8")
    locked.chmod(0o444)
    library._remove_clone_dir(dest)
    assert dest.exists() is False
