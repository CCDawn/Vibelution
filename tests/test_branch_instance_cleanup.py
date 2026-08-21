from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.launcher import app as launcher_app
from core.launcher import branch_instance_cleanup as cleanup
from core.launcher import service as launcher_service
from core.runtime_manager import instances_registry as registry


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "cleanup@example.local")
    _git(root, "config", "user.name", "Cleanup Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def _item(**overrides):
    item = {
        "id": "worktree:task",
        "kind": "worktree",
        "branch": "codex/task",
        "path": "",
        "displayPath": ".worktrees/task",
        "head": "",
        "current": False,
        "legacy": False,
        "dirty": False,
        "checkedOut": True,
        "alive": False,
        "shortName": "task",
    }
    item.update(overrides)
    return item


def test_annotate_marks_main_protected_and_lists_risks():
    payload = {
        "integrationRoot": ".",
        "items": [
            _item(id="main", kind="main", branch="main", current=True, shortName="主"),
            _item(id="worktree:dirty", dirty=True, alive=True, head="abc123"),
        ],
    }

    annotated = cleanup.annotate_cleanup_metadata(payload, integration_root=Path("."))

    main, dirty = annotated["items"]
    assert main["cleanupEligible"] is False
    assert dirty["cleanupEligible"] is True
    assert cleanup.RISK_DISCARD_DIRTY in dirty["cleanupRisks"]
    assert cleanup.RISK_STOP_THEN_REMOVE in dirty["cleanupRisks"]
    assert cleanup.RISK_DELETE_UNMERGED in dirty["cleanupRisks"]


def test_annotate_reuses_merged_ref_lookup_instead_of_per_item_merge_base(tmp_path, monkeypatch):
    root = _init_repo(tmp_path / "repo")
    head = _git(root, "rev-parse", "--short=12", "HEAD")
    calls: list[tuple[str, ...]] = []
    real = cleanup._run_git

    def wrapped(git_root, *args, **kwargs):
        calls.append(args)
        return real(git_root, *args, **kwargs)

    monkeypatch.setattr(cleanup, "_run_git", wrapped)
    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(id="local_branch:one", kind="local_branch", branch="codex/one", head=head),
            _item(id="local_branch:two", kind="local_branch", branch="codex/two", head=head),
            _item(id="local_branch:three", kind="local_branch", branch="codex/three", head=head),
        ],
    }

    annotated = cleanup.annotate_cleanup_metadata(payload, integration_root=root)

    assert all(item["mergedToMain"] is True for item in annotated["items"])
    assert [args for args in calls if args and args[0] == "for-each-ref"]
    assert [args for args in calls if args and args[0] == "merge-base"] == []


def test_annotate_cleanup_skips_merge_base_when_git_budget_expires(monkeypatch):
    def slow_tips(root, *, timeout=15.0):
        time.sleep(0.05)
        return set()

    monkeypatch.setattr(cleanup, "_merged_main_tip_names", slow_tips)
    monkeypatch.setattr(
        cleanup,
        "_unique_commits_merged_to_main",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("merge-base must not run after budget")),
    )
    payload = {
        "integrationRoot": ".",
        "items": [_item(id="worktree:slow", head="abc1234def")],
    }

    annotated = cleanup.annotate_cleanup_metadata(payload, integration_root=Path("."), git_timeout=0.01)

    assert annotated["items"][0]["mergedToMain"] is False
    assert annotated["items"][0]["cleanupEligible"] is True


def test_annotate_unique_unmerged_head_uses_one_ancestor_check(tmp_path, monkeypatch):
    root = _init_repo(tmp_path / "repo")
    _git(root, "checkout", "-b", "codex/topic")
    (root / "README.md").write_text("topic\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "topic")
    topic_head = _git(root, "rev-parse", "--short=12", "HEAD")
    _git(root, "checkout", "main")
    calls: list[tuple[str, ...]] = []
    real = cleanup._run_git

    def wrapped(git_root, *args, **kwargs):
        calls.append(args)
        return real(git_root, *args, **kwargs)

    monkeypatch.setattr(cleanup, "_run_git", wrapped)
    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(id="worktree:a", branch="codex/topic", head=topic_head),
            _item(id="worktree:b", branch="codex/topic", head=topic_head),
        ],
    }

    annotated = cleanup.annotate_cleanup_metadata(payload, integration_root=root)

    assert annotated["items"][0]["mergedToMain"] is False
    assert annotated["items"][1]["mergedToMain"] is False
    assert len([args for args in calls if args and args[0] == "merge-base"]) == 1


def test_annotate_distinct_unmerged_heads_use_one_ancestor_each(tmp_path, monkeypatch):
    root = _init_repo(tmp_path / "repo")
    _git(root, "checkout", "-b", "codex/one")
    (root / "README.md").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "one")
    head_one = _git(root, "rev-parse", "--short=12", "HEAD")
    _git(root, "checkout", "main")
    _git(root, "checkout", "-b", "codex/two")
    (root / "README.md").write_text("two\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "two")
    head_two = _git(root, "rev-parse", "--short=12", "HEAD")
    _git(root, "checkout", "main")
    calls: list[tuple[str, ...]] = []
    lock = threading.Lock()
    real = cleanup._run_git

    def wrapped(git_root, *args, **kwargs):
        with lock:
            calls.append(args)
        return real(git_root, *args, **kwargs)

    monkeypatch.setattr(cleanup, "_run_git", wrapped)
    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(id="worktree:one", branch="codex/one", head=head_one),
            _item(id="worktree:two", branch="codex/two", head=head_two),
            _item(id="local_branch:one", kind="local_branch", branch="codex/one", head=head_one),
        ],
    }

    annotated = cleanup.annotate_cleanup_metadata(payload, integration_root=root)

    assert all(item["mergedToMain"] is False for item in annotated["items"])
    merge_base = [args for args in calls if args and args[0] == "merge-base"]
    assert len(merge_base) == 2
    assert {args[2] for args in merge_base} == {head_one, head_two}


def test_cleanup_requires_confirm_and_ids():
    with pytest.raises(cleanup.BranchInstanceCleanupError) as missing_confirm:
        cleanup.cleanup_branch_instances(["worktree:task"], confirm=False)
    assert missing_confirm.value.code == "confirm_required"

    with pytest.raises(cleanup.BranchInstanceCleanupError) as missing_ids:
        cleanup.cleanup_branch_instances([], confirm=True)
    assert missing_ids.value.code == "instance_ids_required"


def test_cleanup_does_not_eagerly_annotate_metadata(monkeypatch):
    payload = {
        "integrationRoot": ".",
        "items": [_item(id="worktree:task", branch="", checkedOut=False, path="")],
    }

    monkeypatch.setattr(
        cleanup,
        "annotate_cleanup_metadata",
        lambda *_args, **_kwargs: pytest.fail("cleanup must not run the metadata Git scan"),
    )
    monkeypatch.setattr(cleanup, "_drop_registry_instance", lambda _instance_id: True)

    result = cleanup.cleanup_branch_instances(["worktree:task"], confirm=True, list_payload=payload)

    assert result["ok"] is True
    assert [item["id"] for item in result["cleaned"]] == ["worktree:task"]


def test_cleanup_skips_registry_in_flight_instance_without_stopping_or_removing(tmp_path):
    root = _init_repo(tmp_path / "repo")
    worktree = root / ".worktrees" / "starting-task"
    payload = {
        "integrationRoot": str(root),
        "items": [_item(id="worktree:starting-task", path=str(worktree), status="starting")],
    }
    stops: list[str] = []

    result = cleanup.cleanup_branch_instances(
        ["worktree:starting-task"],
        confirm=True,
        list_payload=payload,
        stop_runner=lambda item: stops.append(item["id"]) or {},
    )

    assert result["cleaned"] == []
    assert result["skipped"][0]["code"] == "instance_in_flight"
    assert stops == []
    assert not worktree.exists()


def test_cleanup_reports_registry_drop_failure_and_releases_cleanup_fence(tmp_path, monkeypatch):
    root = _init_repo(tmp_path / "repo")
    payload = {
        "integrationRoot": str(root),
        "items": [_item(id="worktree:task", branch="", checkedOut=False, path="")],
    }
    released: list[tuple[str, str]] = []
    monkeypatch.setattr(cleanup, "_claim_cleanup_instance", lambda _instance_id: (True, "token-1"))
    monkeypatch.setattr(cleanup, "_drop_registry_instance", lambda _instance_id: False)
    monkeypatch.setattr(
        cleanup,
        "_release_cleanup_instance",
        lambda instance_id, token: released.append((instance_id, token)),
    )

    result = cleanup.cleanup_branch_instances(["worktree:task"], confirm=True, list_payload=payload)

    assert result["ok"] is False
    assert result["cleaned"] == []
    assert result["failed"][0]["code"] == "instance_cleanup_failed"
    assert released == [("worktree:task", "token-1")]


def test_cleanup_fence_blocks_claim_start_until_real_registry_release(tmp_path, monkeypatch):
    registry_path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: registry_path)
    monkeypatch.setattr(registry, "_port_is_free", lambda _port, host=None: True)
    instance_id = "worktree:task"

    registry.mutate_registry(
        lambda payload: registry.apply_upsert(
            payload,
            instance_id,
            {
                "projectRoot": str(tmp_path / "repo"),
                "status": "steady",
                "phase": "steady",
                "generation": 4,
            },
        )
    )

    claimed, token = cleanup._claim_cleanup_instance(instance_id)

    assert claimed is True
    assert token.startswith("cleanup-")
    fenced = registry.load_registry()["instances"][instance_id]
    assert fenced["cleanupInProgress"] is True
    assert fenced["cleanupToken"] == token

    def claim_start(payload):
        return registry.apply_claim_start(
            payload,
            instance_id=instance_id,
            project_root=str(tmp_path / "repo"),
            branch="codex/task",
            command_id="cmd-start",
            deadline_at="2026-08-22T00:00:00Z",
            owner_pid=1234,
            preferred_backend=19000,
            preferred_control=19001,
        )

    with pytest.raises(registry.InstanceBusyError) as busy:
        registry.mutate_registry(claim_start)
    assert busy.value.code == "instance_busy"
    assert busy.value.status == "cleanup"

    cleanup._release_cleanup_instance(instance_id, token)
    released = registry.load_registry()["instances"][instance_id]
    assert "cleanupInProgress" not in released
    assert "cleanupToken" not in released

    started = registry.mutate_registry(claim_start)
    assert started["status"] == "starting"
    assert started["phase"] == "starting"
    assert started["generation"] == 5


def test_drop_registry_instance_uses_locked_mutation(monkeypatch):
    calls: list[str] = []

    def mutate(mutator):
        calls.append("mutate")
        payload = {"instances": {"worktree:task": {"status": "closed"}}}
        assert mutator(payload) is True
        assert "worktree:task" not in payload["instances"]
        return True

    monkeypatch.setattr(cleanup.registry, "mutate_registry", mutate)
    monkeypatch.setattr(
        cleanup.registry,
        "load_registry",
        lambda: pytest.fail("registry cleanup must not use an unlocked load"),
    )
    monkeypatch.setattr(
        cleanup.registry,
        "save_registry",
        lambda *_args, **_kwargs: pytest.fail("registry cleanup must not use an unlocked save"),
    )

    assert cleanup._drop_registry_instance("worktree:task") is True
    assert calls == ["mutate"]


def test_cleanup_refuses_main_and_current(tmp_path):
    root = _init_repo(tmp_path / "repo")
    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(id="main", kind="main", branch="main", current=True, path=str(root), shortName="主"),
            _item(id="worktree:current", branch="codex/current", current=True, path=str(root)),
        ],
    }

    result = cleanup.cleanup_branch_instances(
        ["main", "worktree:current"],
        confirm=True,
        list_payload=payload,
    )

    assert result["cleaned"] == []
    assert {item["code"] for item in result["skipped"]} == {"instance_protected"}
    assert (root / "README.md").read_text(encoding="utf-8") == "base\n"
    assert _git(root, "branch", "--show-current") == "main"


def test_cleanup_removes_retired_leftover_with_windows_long_path(tmp_path):
    import os

    root = _init_repo(tmp_path / "repo")
    leftover = root / ".worktrees" / "_retired" / "chat-status-rail-topbar-polish"
    nested = leftover / "logs" / "runtime_scenes" / ("s" * 40) / "sessions" / ("session-" + "x" * 40) / "turns" / ("turn-" + "y" * 50)
    os.makedirs(cleanup._os_remove_target(nested), exist_ok=True)
    with open(cleanup._os_remove_target(nested / "execution_registry.jsonl"), "w", encoding="utf-8") as handle:
        handle.write("{}\n")

    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(
                id="retired:chat-status-rail-topbar-polish",
                kind="retired",
                branch="",
                path=str(leftover),
                checkedOut=False,
                shortName="polish",
            )
        ],
    }

    result = cleanup.cleanup_branch_instances(
        ["retired:chat-status-rail-topbar-polish"],
        confirm=True,
        list_payload=payload,
    )

    assert result["ok"] is True
    assert result["cleaned"][0]["actions"] == ["worktree_removed"]
    assert not leftover.exists()


def test_remove_directory_removes_symlink_entry_without_touching_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    cleanup._remove_directory(link)

    assert not os.path.lexists(str(link))
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_cleanup_deletes_unmerged_local_branch_without_touching_remote(tmp_path):
    root = _init_repo(tmp_path / "repo")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-u", "origin", "main")
    _git(root, "branch", "codex/abandoned")
    _git(root, "push", "origin", "codex/abandoned")

    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(
                id="branch:codex/abandoned",
                kind="local_branch",
                branch="codex/abandoned",
                checkedOut=False,
                path="",
                head=_git(root, "rev-parse", "--short", "codex/abandoned"),
                shortName="abandoned",
            )
        ],
    }
    git_calls: list[tuple[str, ...]] = []
    real_run = cleanup._run_git

    def spy(root_path, *args, timeout=30.0):
        git_calls.append(tuple(str(arg) for arg in args))
        return real_run(root_path, *args, timeout=timeout)

    cleanup._run_git = spy  # type: ignore[method-assign]
    try:
        result = cleanup.cleanup_branch_instances(
            ["branch:codex/abandoned"],
            confirm=True,
            list_payload=payload,
        )
    finally:
        cleanup._run_git = real_run  # type: ignore[method-assign]

    assert result["ok"] is True
    assert result["cleaned"][0]["actions"] == ["branch_deleted"]
    local_branches = _git(root, "branch")
    assert "codex/abandoned" not in local_branches
    remote_branches = _git(root, "ls-remote", "--heads", "origin")
    assert "codex/abandoned" in remote_branches
    assert "push" not in {call[0] for call in git_calls}


def test_cleanup_stops_then_force_removes_dirty_unmerged_worktree(tmp_path):
    root = _init_repo(tmp_path / "repo")
    worktree = root / ".worktrees" / "dirty-task"
    worktree.parent.mkdir(parents=True)
    _git(root, "worktree", "add", "-b", "codex/dirty-task", str(worktree))
    (worktree / "scratch.txt").write_text("dirty\n", encoding="utf-8")
    _git(worktree, "add", "scratch.txt")
    _git(worktree, "commit", "-m", "unmerged")
    (worktree / "local-only.txt").write_text("unstaged\n", encoding="utf-8")
    stops: list[str] = []

    payload = {
        "integrationRoot": str(root),
        "items": [
            _item(
                id="worktree:dirty-task",
                branch="codex/dirty-task",
                path=str(worktree),
                dirty=True,
                alive=True,
                checkedOut=True,
                head=_git(worktree, "rev-parse", "--short", "HEAD"),
                shortName="dirty-task",
            )
        ],
    }

    result = cleanup.cleanup_branch_instances(
        ["worktree:dirty-task"],
        confirm=True,
        list_payload=payload,
        stop_runner=lambda item: stops.append(item["id"]) or {"accepted": True},
    )

    assert stops == ["worktree:dirty-task"]
    assert result["ok"] is True
    assert result["cleaned"][0]["actions"] == ["stopped", "worktree_removed", "branch_deleted"]
    assert not worktree.exists()
    assert "codex/dirty-task" not in _git(root, "branch")
    assert _git(root, "branch", "--show-current") == "main"


def test_standalone_cleanup_route_requires_confirm(monkeypatch):
    def fail(*_args, **_kwargs):
        raise cleanup.BranchInstanceCleanupError("confirm_required", "清理需要确认。")

    monkeypatch.setattr(launcher_service, "cleanup_launcher_branch_instances", fail)
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post(
        "/api/launcher/branch-instances/cleanup",
        json={"instanceIds": ["worktree:task"], "confirm": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "confirm_required"


def test_standalone_cleanup_route_applies_batch(monkeypatch):
    calls: list[tuple[tuple[str, ...], bool]] = []

    def apply(instance_ids, *, confirm):
        calls.append((tuple(instance_ids), confirm))
        return {
            "ok": True,
            "cleaned": [{"id": instance_ids[0], "actions": ["branch_deleted"]}],
            "failed": [],
            "skipped": [],
        }

    monkeypatch.setattr(launcher_service, "cleanup_launcher_branch_instances", apply)
    client = TestClient(launcher_app.create_launcher_app())

    response = client.post(
        "/api/launcher/branch-instances/cleanup",
        json={"instanceIds": ["branch:codex/task"], "confirm": True},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert calls == [(("branch:codex/task",), True)]
