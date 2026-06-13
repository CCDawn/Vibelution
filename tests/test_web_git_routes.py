from types import SimpleNamespace

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import git as git_routes
from core.web.services import git_status_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_git_status_endpoint_exposes_read_only_worktree_snapshot(monkeypatch):
    class FakeGitStatusService:
        def scan_working_tree(self, store=False):
            assert store is False
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/app/AppShell.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    ),
                    SimpleNamespace(
                        path="core/web/routes/git.py",
                        status="??",
                        staged=False,
                        unstaged=False,
                        untracked=True,
                        deleted=False,
                        old_path=None,
                    ),
                ],
            )

        def _git_head_rev(self):
            return "abcdef1234567890"

        def _run_git(self, args):
            if args == ["branch", "--show-current"]:
                return SimpleNamespace(returncode=0, stdout="codex/git-navbar\n")
            if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
                return SimpleNamespace(returncode=0, stdout="origin/codex/git-navbar\n")
            if args == ["rev-list", "--left-right", "--count", "origin/codex/git-navbar...HEAD"]:
                return SimpleNamespace(returncode=0, stdout="1\t2\n")
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/status", params={"limit": 1})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert payload["branch"] == "codex/git-navbar"
    assert payload["headRevShort"] == "abcdef123456"
    assert payload["upstream"]["name"] == "origin/codex/git-navbar"
    assert payload["upstream"]["ahead"] == 2
    assert payload["upstream"]["behind"] == 1
    assert payload["dirty"] is True
    assert payload["counts"] == {
        "total": 2,
        "staged": 0,
        "unstaged": 1,
        "untracked": 1,
        "deleted": 0,
    }
    assert payload["files"][0]["path"] == "web/src/app/AppShell.tsx"
    assert payload["files"][0]["statusLabel"] == "modified"
    assert payload["totalFiles"] == 2
    assert payload["truncated"] is True


def test_git_status_endpoint_reports_unavailable(monkeypatch):
    class FakeUnavailableGitStatusService:
        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=False,
                error="not a git repository",
                snapshot_id="unavailable",
                created_at="2026-05-21T10:00:00",
                base_rev=None,
                files=[],
            )

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeUnavailableGitStatusService())

    response = client.get("/api/git/status")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is False
    assert payload["dirty"] is False
    assert payload["summary"] == "Git unavailable: not a git repository"
    assert payload["error"] == "not a git repository"
    assert payload["files"] == []


def test_git_commits_endpoint_exposes_recent_commits(monkeypatch):
    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def _run_git(self, args):
            assert args == [
                "log",
                "--max-count=2",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
            ]
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "abcdef1234567890\x1fabcdef1\x1fAgent\x1f2026-05-21T10:00:00+08:00\x1ffeat: git page\n"
                    "1111111111111111\x1f1111111\x1fAgent\x1f2026-05-20T10:00:00+08:00\x1ffix: prior"
                ),
                stderr="",
            )

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/commits", params={"limit": 2})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert [item["shortSha"] for item in payload["commits"]] == ["abcdef1", "1111111"]
    assert payload["commits"][0]["subject"] == "feat: git page"


def test_git_diff_endpoint_exposes_file_diff(monkeypatch):
    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/routes/GitRoute.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    )
                ],
            )

        def _run_git(self, args):
            if args == ["diff", "--cached", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args == ["diff", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="diff --git a/web/src/routes/GitRoute.tsx b/web/src/routes/GitRoute.tsx\n+page\n",
                    stderr="",
                )
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.get("/api/git/diff", params={"path": "web/src/routes/GitRoute.tsx"})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["available"] is True
    assert payload["path"] == "web/src/routes/GitRoute.tsx"
    assert payload["language"] == "diff"
    assert "# unstaged" in payload["diff"]
    assert payload["statusLabel"] == "modified"


def test_git_diff_endpoint_rejects_path_escape():
    response = client.get("/api/git/diff", params={"path": "../secret.txt"})

    assert response.status_code == 400
    assert "project root" in response.json()["detail"]


def test_git_commit_message_endpoint_generates_ai_draft(monkeypatch):
    captured_profiles = []

    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/routes/GitRoute.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    )
                ],
            )

        def _run_git(self, args):
            if args == ["diff", "--cached", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if args == ["diff", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="diff --git a/web/src/routes/GitRoute.tsx b/web/src/routes/GitRoute.tsx\n+commit ui\n",
                    stderr="",
                )
            if args == ["branch", "--show-current"]:
                return SimpleNamespace(returncode=0, stdout="codex/git-page\n", stderr="")
            raise AssertionError(args)

    class FakeLlmClient:
        def invoke(self, messages, tools=None, metadata=None):
            assert metadata["selected_paths"] == ["web/src/routes/GitRoute.tsx"]
            assert "commit ui" in messages[-1]["content"]
            assert tools is None
            return SimpleNamespace(content="feat: add git commit controls")

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())
    monkeypatch.setattr(
        git_status_service,
        "load_public_config",
        lambda: {
            "llm": {
                "model_library": {
                    "local_commit_model": {
                        "provider": {
                            "kind": "local",
                            "api_key_env": "",
                            "base_url": "http://localhost:11434/v1",
                            "compat_mode": "openai",
                            "requires_api_key": False,
                            "context_window": 65536,
                        },
                        "model": "local-model",
                        "contract": "basic_chat",
                        "strict_compatibility": False,
                    },
                },
                "profiles": {
                    "primary": {
                        "model_ref": "local_commit_model",
                    },
                    "subagent_explorer": {
                        "model_ref": "local_commit_model",
                    },
                }
            },
            "git": {
                "commit_message_model_ref": "local_commit_model",
                "commit_message_prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}",
            },
        },
    )
    monkeypatch.setattr(git_status_service, "build_effective_config", lambda public_config: SimpleNamespace())
    monkeypatch.setattr(
        git_status_service,
        "get_llm_client",
        lambda profile_id=None, config=None: captured_profiles.append(profile_id) or FakeLlmClient(),
    )

    response = client.post(
        "/api/git/commit-message",
        json={"paths": ["web/src/routes/GitRoute.tsx"], "modelId": "local_commit_model"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["message"] == "feat: add git commit controls"
    assert payload["modelId"] == "local_commit_model"
    assert "profileId" not in payload
    assert payload["files"] == ["web/src/routes/GitRoute.tsx"]
    assert captured_profiles == [git_status_service.GIT_COMMIT_MESSAGE_PROFILE_ID]


def test_git_commit_message_default_model_endpoint_persists_selection(monkeypatch):
    monkeypatch.setattr(
        git_routes,
        "update_git_commit_message_model",
        lambda model_id: {"modelId": model_id, "previousModelId": "old_model"},
    )

    response = client.put("/api/git/commit-message/default-model", json={"modelId": "new_model"})

    assert response.status_code == 200, response.json()
    assert response.json() == {"modelId": "new_model", "previousModelId": "old_model"}


def test_git_commit_message_default_model_endpoint_rejects_unknown_model(monkeypatch):
    def fake_update(model_id):
        raise ValueError(f"unknown Git commit message model: {model_id}")

    monkeypatch.setattr(git_routes, "update_git_commit_message_model", fake_update)

    response = client.put("/api/git/commit-message/default-model", json={"modelId": "missing_model"})

    assert response.status_code == 422
    assert "unknown Git commit message model" in response.json()["detail"]


def test_git_commit_message_prompt_endpoint_updates_template(monkeypatch):
    monkeypatch.setattr(
        git_routes,
        "update_git_commit_message_prompt",
        lambda prompt: {"prompt": prompt, "previousPromptChars": 3, "promptChars": len(prompt)},
    )

    response = client.put("/api/git/commit-message/prompt", json={"prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}"})

    assert response.status_code == 200, response.json()
    assert response.json()["promptChars"] == len("Summary: {summary}\nFiles: {files}\nDiff: {diff}")


def test_git_commit_message_prompt_endpoint_rejects_invalid_template(monkeypatch):
    def fake_update(prompt):
        raise ValueError("Git commit message prompt must include: {diff}")

    monkeypatch.setattr(git_routes, "update_git_commit_message_prompt", fake_update)

    response = client.put("/api/git/commit-message/prompt", json={"prompt": "Summary: {summary}"})

    assert response.status_code == 422
    assert "{diff}" in response.json()["detail"]


def test_git_commit_endpoint_rejects_empty_message():
    response = client.post("/api/git/commit", json={"paths": ["web/src/routes/GitRoute.tsx"], "message": ""})

    assert response.status_code == 422
    assert "Commit message is required" in response.json()["detail"]


def test_git_commit_endpoint_rejects_path_escape():
    response = client.post("/api/git/commit", json={"paths": ["../secret.txt"], "message": "feat: nope"})

    assert response.status_code == 422
    assert "project root" in response.json()["detail"]


def test_git_commit_endpoint_rejects_unselected_staged_files(monkeypatch):
    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/routes/GitRoute.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    ),
                    SimpleNamespace(
                        path="core/web/routes/git.py",
                        status="M ",
                        staged=True,
                        unstaged=False,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    ),
                ],
            )

        def _run_git(self, args):
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.post(
        "/api/git/commit",
        json={"paths": ["web/src/routes/GitRoute.tsx"], "message": "feat: selected only"},
    )

    assert response.status_code == 422
    assert "staged files outside" in response.json()["detail"]


def test_git_commit_endpoint_commits_selected_files(monkeypatch):
    calls = []

    class FakeGitStatusService:
        def is_git_available(self):
            return True, None

        def scan_working_tree(self, store=False):
            return SimpleNamespace(
                available=True,
                error=None,
                snapshot_id="wt-test",
                created_at="2026-05-21T10:00:00",
                base_rev="abcdef1234567890",
                files=[
                    SimpleNamespace(
                        path="web/src/routes/GitRoute.tsx",
                        status=" M",
                        staged=False,
                        unstaged=True,
                        untracked=False,
                        deleted=False,
                        old_path=None,
                    )
                ],
            )

        def _run_git(self, args):
            calls.append(args)
            if args == ["commit", "-m", "feat: selected git commit", "--", "web/src/routes/GitRoute.tsx"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout="[branch abcdef1] feat: selected git commit\n 1 file changed\n",
                    stderr="",
                )
            if args == ["rev-parse", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout="abcdef1234567890\n", stderr="")
            raise AssertionError(args)

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: FakeGitStatusService())

    response = client.post(
        "/api/git/commit",
        json={"paths": ["web/src/routes/GitRoute.tsx"], "message": "feat: selected git commit"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["committed"] is True
    assert payload["shortSha"] == "abcdef123456"
    assert calls == [
        ["commit", "-m", "feat: selected git commit", "--", "web/src/routes/GitRoute.tsx"],
        ["rev-parse", "HEAD"],
    ]
