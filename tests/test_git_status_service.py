from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from config.public_config import HEADER_LINES, load_public_config, save_public_config
from config.toml_writer import dumps_public_config
from core.web.services import git_status_service


class FakeGitService:
    def __init__(self, files, results=None):
        self.files = list(files)
        self.results = dict(results or {})
        self.calls: list[list[str]] = []
        self.scan_calls = 0

    def is_git_available(self):
        return True, None

    def scan_working_tree(self, store=False):
        self.scan_calls += 1
        return SimpleNamespace(
            available=True,
            error=None,
            snapshot_id="wt-test",
            created_at="2026-05-21T10:00:00",
            base_rev="abcdef1234567890",
            files=list(self.files),
        )

    def _run_git(self, args):
        self.calls.append(list(args))
        key = tuple(args)
        if key in self.results:
            return self.results[key]
        raise AssertionError(args)


@pytest.fixture(autouse=True)
def clear_git_status_cache():
    git_status_service._clear_git_status_cache()
    yield
    git_status_service._clear_git_status_cache()


def changed_file(path: str, status: str = " M", **overrides):
    payload = {
        "path": path,
        "status": status,
        "staged": status[0] != " " if len(status) >= 1 else False,
        "unstaged": status[1] != " " if len(status) >= 2 else False,
        "untracked": status == "??",
        "deleted": "D" in status,
        "old_path": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def ok(stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)


def failed(stderr: str):
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


def test_get_git_status_reuses_cached_snapshot_and_metadata_within_ttl(monkeypatch):
    service = FakeGitService(
        [
            changed_file("web/src/routes/GitRoute.tsx"),
            changed_file("core/web/services/git_status_service.py"),
        ],
        results={
            ("branch", "--show-current"): ok("codex/git-status-cache\n"),
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): ok("origin/codex/git-status-cache\n"),
            ("rev-list", "--left-right", "--count", "origin/codex/git-status-cache...HEAD"): ok("0\t1\n"),
            (
                "log",
                "--max-count=5",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
                "origin/codex/git-status-cache..HEAD",
            ): ok(),
            ("worktree", "list", "--porcelain"): ok(),
            ("branch", "--no-merged", "main", "--format=%(refname:short)"): ok(),
        },
    )
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)
    monkeypatch.setattr(git_status_service, "_monotonic", lambda: 100.0)

    first = git_status_service.get_git_status(limit=1)
    second = git_status_service.get_git_status(limit=500)

    assert service.scan_calls == 1
    assert service.calls == [
        ["branch", "--show-current"],
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        ["rev-list", "--left-right", "--count", "origin/codex/git-status-cache...HEAD"],
        [
            "log",
            "--max-count=5",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
            "origin/codex/git-status-cache..HEAD",
        ],
        ["worktree", "list", "--porcelain"],
        ["branch", "--no-merged", "main", "--format=%(refname:short)"],
    ]
    assert first["totalFiles"] == 2
    assert first["truncated"] is True
    assert len(first["files"]) == 1
    assert second["totalFiles"] == 2
    assert second["truncated"] is False
    assert len(second["files"]) == 2
    assert second["upstream"] == {
        "name": "origin/codex/git-status-cache",
        "remote": "origin",
        "ahead": 1,
        "behind": 0,
        "hasUpstream": True,
    }


def test_get_git_status_refreshes_working_tree_after_ttl_without_repeating_metadata(monkeypatch):
    service = FakeGitService(
        [changed_file("web/src/routes/GitRoute.tsx")],
        results={
            ("branch", "--show-current"): ok("codex/git-status-cache\n"),
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): ok("origin/codex/git-status-cache\n"),
            ("rev-list", "--left-right", "--count", "origin/codex/git-status-cache...HEAD"): ok("0\t1\n"),
            (
                "log",
                "--max-count=5",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
                "origin/codex/git-status-cache..HEAD",
            ): ok(),
            ("worktree", "list", "--porcelain"): ok(),
            ("branch", "--no-merged", "main", "--format=%(refname:short)"): ok(),
        },
    )
    ticks = iter([100.0, 100.0, 102.0, 102.0])
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)
    monkeypatch.setattr(git_status_service, "_monotonic", lambda: next(ticks))

    first = git_status_service.get_git_status()
    service.files = [
        changed_file("web/src/routes/GitRoute.tsx"),
        changed_file("core/web/services/git_status_service.py"),
    ]
    second = git_status_service.get_git_status()

    assert service.scan_calls == 2
    assert service.calls == [
        ["branch", "--show-current"],
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        ["rev-list", "--left-right", "--count", "origin/codex/git-status-cache...HEAD"],
        [
            "log",
            "--max-count=5",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%aN%x1f%aI%x1f%s",
            "origin/codex/git-status-cache..HEAD",
        ],
        ["worktree", "list", "--porcelain"],
        ["branch", "--no-merged", "main", "--format=%(refname:short)"],
    ]
    assert first["totalFiles"] == 1
    assert second["totalFiles"] == 2


def test_commit_git_changes_rejects_windows_absolute_paths(monkeypatch):
    service = FakeGitService([changed_file("web/src/routes/GitRoute.tsx")])
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)

    with pytest.raises(ValueError, match="project root"):
        git_status_service.commit_git_changes([r"C:\Users\17533\secret.txt"], "feat: nope")

    assert service.calls == []


def test_get_git_object_detail_rejects_unsafe_commit_ref(monkeypatch):
    service = FakeGitService([])
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)

    with pytest.raises(ValueError, match="hexadecimal SHA"):
        git_status_service.get_git_object_detail("commit", "--help")

    assert service.calls == []


def test_get_git_object_detail_exposes_registered_worktree_status(monkeypatch):
    worktree_path = "C:/Users/17533/Desktop/Vibelution-worktrees/demo"
    service = FakeGitService(
        [],
        results={
            ("worktree", "list", "--porcelain"): ok(
                f"worktree {worktree_path}\n"
                "HEAD 1111111111111111\n"
                "branch refs/heads/codex/demo\n"
            ),
            ("-C", worktree_path, "status", "--short", "--branch"): ok("## codex/demo\n M web/src/routes/GitRoute.tsx\n"),
            ("check-ref-format", "--branch", "codex/demo"): ok("codex/demo\n"),
            ("rev-list", "--left-right", "--count", "main...codex/demo"): ok("3\t2\n"),
            ("diff", "--stat", "--patch", "--no-ext-diff", "--no-color", "main...codex/demo"): ok(
                "diff --git a/web/src/routes/GitRoute.tsx b/web/src/routes/GitRoute.tsx\n+detail\n"
            ),
            ("-C", worktree_path, "diff", "--cached", "--no-ext-diff", "--no-color"): ok(""),
            ("-C", worktree_path, "diff", "--no-ext-diff", "--no-color"): ok(""),
        },
    )
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)

    payload = git_status_service.get_git_object_detail("worktree", "codex/demo", worktree_path)

    assert payload["available"] is True
    assert payload["kind"] == "worktree"
    assert payload["statusLabel"] == "worktree"
    assert payload["meta"]["branch"] == "codex/demo"
    assert payload["meta"]["aheadMain"] == 2
    assert "# status" in payload["diff"]
    assert "# branch diff main...worktree" in payload["diff"]
    assert "web/src/routes/GitRoute.tsx" in payload["diff"]


def test_commit_git_changes_stages_selected_untracked_files(monkeypatch):
    service = FakeGitService(
        [changed_file("notes/new-plan.md", status="??")],
        results={
            ("add", "--", "notes/new-plan.md"): ok(),
            ("commit", "-m", "docs: add plan", "--", "notes/new-plan.md"): ok("[branch abc1234] docs: add plan\n"),
            ("rev-parse", "HEAD"): ok("abcdef1234567890\n"),
        },
    )
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)

    payload = git_status_service.commit_git_changes(["notes/new-plan.md"], "docs: add plan")

    assert payload["committed"] is True
    assert payload["files"] == ["notes/new-plan.md"]
    assert service.calls == [
        ["add", "--", "notes/new-plan.md"],
        ["commit", "-m", "docs: add plan", "--", "notes/new-plan.md"],
        ["rev-parse", "HEAD"],
    ]


def test_commit_git_changes_propagates_git_commit_failure(monkeypatch):
    service = FakeGitService(
        [changed_file("web/src/routes/GitRoute.tsx")],
        results={
            ("commit", "-m", "feat: selected git commit", "--", "web/src/routes/GitRoute.tsx"): failed(
                "nothing added to commit"
            ),
        },
    )
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)

    with pytest.raises(ValueError, match="nothing added to commit"):
        git_status_service.commit_git_changes(["web/src/routes/GitRoute.tsx"], "feat: selected git commit")

    assert service.calls == [
        ["commit", "-m", "feat: selected git commit", "--", "web/src/routes/GitRoute.tsx"],
    ]


def test_commit_git_changes_records_failed_commit_event_without_message(monkeypatch):
    service = FakeGitService(
        [changed_file("web/src/routes/GitRoute.tsx")],
        results={
            ("commit", "-m", "feat: private failure subject", "--", "web/src/routes/GitRoute.tsx"): failed(
                "nothing added to commit"
            ),
        },
    )
    events = []
    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)
    monkeypatch.setattr(
        git_status_service,
        "_record_git_scene_event",
        lambda phase, event_code, **kwargs: events.append(
            {
                "phase": phase,
                "event_code": event_code,
                **kwargs,
            }
        ),
    )

    with pytest.raises(ValueError, match="nothing added to commit"):
        git_status_service.commit_git_changes(["web/src/routes/GitRoute.tsx"], "feat: private failure subject")

    commit_events = [event for event in events if event["event_code"] == "git.commit.failed"]
    assert len(commit_events) == 1
    assert commit_events[0]["phase"] == "commit"
    assert commit_events[0]["level"] == "error"
    assert commit_events[0]["outcome"] == "failed"
    assert commit_events[0]["fields"]["selectedPaths"] == ["web/src/routes/GitRoute.tsx"]
    assert commit_events[0]["fields"]["selectedFileCount"] == 1
    assert "feat: private failure subject" not in json.dumps(events)
    assert any(
        event["event_code"] == "git.command.failed"
        and event["fields"]["args"] == ["commit", "-m", "[redacted]", "--", "web/src/routes/GitRoute.tsx"]
        for event in events
    )


def test_generate_git_commit_message_cleans_fenced_ai_output(monkeypatch):
    service = FakeGitService(
        [changed_file("web/src/routes/GitRoute.tsx")],
        results={
            ("diff", "--cached", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"): ok(),
            ("diff", "--no-ext-diff", "--no-color", "--", "web/src/routes/GitRoute.tsx"): ok(
                "diff --git a/web/src/routes/GitRoute.tsx b/web/src/routes/GitRoute.tsx\n+commit controls\n"
            ),
            ("branch", "--show-current"): ok("codex/git-page\n"),
        },
    )

    class FakeLlmClient:
        def invoke(self, messages, tools=None, metadata=None):
            assert tools in (None, [])
            assert metadata["selected_paths"] == ["web/src/routes/GitRoute.tsx"]
            assert "commit controls" in messages[-1]["content"]
            return SimpleNamespace(content="```text\nfeat: add git commit controls\n```")

    monkeypatch.setattr(git_status_service, "get_git_memory_service", lambda: service)
    monkeypatch.setattr(
        git_status_service,
        "load_public_config",
        lambda: {
            "llm": {
                "profiles": {"primary": {"model_ref": "local_commit_model"}},
                "model_library": {
                    "local_commit_model": {
                        "provider": {
                            "kind": "local",
                            "api_key_env": "",
                            "base_url": "http://localhost:11434/v1",
                            "compat_mode": "openai",
                            "requires_api_key": False,
                        },
                        "model": "local-model",
                        "contract": "basic_chat",
                        "strict_compatibility": False,
                    }
                },
            },
            "git": {
                "commit_message_model_ref": "local_commit_model",
                "commit_message_prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}",
            },
        },
    )
    monkeypatch.setattr(git_status_service, "build_effective_config", lambda public_config: SimpleNamespace())
    monkeypatch.setattr(git_status_service, "get_llm_client", lambda profile_id=None, config=None: FakeLlmClient())

    payload = git_status_service.generate_git_commit_message(["web/src/routes/GitRoute.tsx"])

    assert payload["message"] == "feat: add git commit controls"
    assert payload["modelId"] == "local_commit_model"
    assert "profileId" not in payload


def test_with_git_config_defaults_does_not_mutate_input_and_recovers_invalid_git_block():
    public_config = {"ui": {"language": "zh"}, "git": "disabled"}

    payload = git_status_service.with_git_config_defaults(public_config)

    assert public_config == {"ui": {"language": "zh"}, "git": "disabled"}
    assert payload["ui"] == {"language": "zh"}
    assert payload["git"]["commit_message_model_ref"] == ""
    assert "{diff}" in payload["git"]["commit_message_prompt"]


def test_with_git_config_defaults_repairs_stale_commit_model_ref_to_primary_model():
    public_config = {
        "llm": {
            "profiles": {"primary": {"model_ref": "current_model"}},
            "model_library": {
                "current_model": {
                    "provider": {"kind": "local", "base_url": "http://localhost:11434/v1", "requires_api_key": False},
                    "model": "current",
                }
            },
        },
        "git": {
            "commit_message_model_ref": "deleted_model",
            "commit_message_prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}",
        },
    }

    payload = git_status_service.with_git_config_defaults(public_config)

    assert public_config["git"]["commit_message_model_ref"] == "deleted_model"
    assert payload["git"]["commit_message_model_ref"] == "current_model"


def test_git_config_defaults_round_trip_through_public_toml(tmp_path):
    config_path = tmp_path / "config.toml"
    public_config = git_status_service.with_git_config_defaults(load_public_config())
    public_config["git"]["commit_message_prompt"] = "Summary: {summary}\n\nFiles:\n{files}\n\nDiff:\n{diff}"
    config_path.write_text(dumps_public_config(public_config, HEADER_LINES), encoding="utf-8")

    save_public_config(public_config, config_path)
    loaded = load_public_config(config_path)

    assert loaded["git"]["commit_message_model_ref"] == public_config["git"]["commit_message_model_ref"]
    assert loaded["git"]["commit_message_prompt"] == public_config["git"]["commit_message_prompt"]


def test_update_git_commit_message_model_persists_model_ref_and_clears_legacy_profile(monkeypatch):
    saved_payloads: list[dict] = []
    public_config = {
        "llm": {
            "profiles": {"primary": {"model_ref": "old_model"}},
            "model_library": {
                "old_model": {
                    "provider": {"kind": "local", "base_url": "http://localhost:11434/v1", "requires_api_key": False},
                    "model": "old",
                },
                "new_model": {
                    "provider": {"kind": "local", "base_url": "http://localhost:11434/v1", "requires_api_key": False},
                    "model": "new",
                },
            },
        },
        "git": {
            "commit_message_profile": "primary",
            "commit_message_model_ref": "old_model",
            "commit_message_prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}",
        },
    }
    monkeypatch.setattr(git_status_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(git_status_service, "build_effective_config", lambda updated: SimpleNamespace())
    monkeypatch.setattr(git_status_service, "save_public_config", lambda updated: saved_payloads.append(copy.deepcopy(updated)))

    payload = git_status_service.update_git_commit_message_model("new_model")

    assert payload == {"modelId": "new_model", "previousModelId": "old_model"}
    assert saved_payloads
    assert saved_payloads[0]["git"]["commit_message_model_ref"] == "new_model"
    assert "commit_message_profile" not in saved_payloads[0]["git"]


def test_update_git_commit_message_model_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(
        git_status_service,
        "load_public_config",
        lambda: {"llm": {"model_library": {}}, "git": {"commit_message_prompt": "Summary: {summary}"}},
    )

    with pytest.raises(ValueError, match="unknown Git commit message model"):
        git_status_service.update_git_commit_message_model("missing_model")


def test_update_git_commit_message_prompt_persists_template(monkeypatch):
    saved_payloads: list[dict] = []
    public_config = {
        "llm": {"model_library": {}},
        "git": {
            "commit_message_model_ref": "",
            "commit_message_prompt": "Summary: {summary}\nFiles: {files}\nDiff: {diff}",
        },
    }
    monkeypatch.setattr(git_status_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(git_status_service, "build_effective_config", lambda updated: SimpleNamespace())
    monkeypatch.setattr(git_status_service, "save_public_config", lambda updated: saved_payloads.append(copy.deepcopy(updated)))

    payload = git_status_service.update_git_commit_message_prompt("New: {summary}\nFiles: {files}\nDiff: {diff}")

    assert payload["prompt"] == "New: {summary}\nFiles: {files}\nDiff: {diff}"
    assert saved_payloads[0]["git"]["commit_message_prompt"] == payload["prompt"]


def test_update_git_commit_message_prompt_requires_placeholders(monkeypatch):
    monkeypatch.setattr(git_status_service, "load_public_config", lambda: {"git": {}})

    with pytest.raises(ValueError, match=r"\{files\}"):
        git_status_service.update_git_commit_message_prompt("Summary: {summary}\nDiff: {diff}")


def test_ai_diff_payload_truncates_large_diffs_without_dropping_summary(monkeypatch):
    service = FakeGitService(
        [changed_file("core/web/services/git_status_service.py")],
        results={
            (
                "diff",
                "--cached",
                "--no-ext-diff",
                "--no-color",
                "--",
                "core/web/services/git_status_service.py",
            ): ok(),
            (
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--",
                "core/web/services/git_status_service.py",
            ): ok("+" + ("x" * (git_status_service.MAX_AI_FILE_DIFF_CHARS + 100))),
        },
    )
    monkeypatch.setattr(git_status_service, "PROJECT_ROOT", Path.cwd())

    payload = git_status_service._ai_diff_payload(
        service,
        [
            {
                "path": "core/web/services/git_status_service.py",
                "status": "M",
                "statusLabel": "modified",
            }
        ],
    )

    assert "M core/web/services/git_status_service.py" in payload["summary"]
    assert "... file diff truncated ..." in payload["diff"]
