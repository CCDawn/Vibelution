"""Exercise Launcher task provisioning against real Git checkouts."""

from pathlib import Path

import pytest

from core.web.services.external_agent.store import ExternalAgentTaskStore
from core.web.services.local_assistant.service import LocalAssistantTaskService
from core.web.services.team.dev_task_board import ensure_dev_task_workspace
from tests.test_dev_task_board import _git, _seed_main_repo
from tests.test_external_agent_task_service import FakeRuntime, _service
from tests.test_local_assistant_tasks import start


@pytest.fixture
def project(tmp_path, monkeypatch):
    path = tmp_path / "project"
    path.mkdir()
    _seed_main_repo(path, monkeypatch)
    return path


def linked_checkout(project, target, *, detached=False):
    mode = ["--detach"] if detached else ["-b", "codex/selected-source"]
    _git(project, ["worktree", "add", *mode, str(target), "main"])
    (target / "branch-only.txt").write_text("selected checkout content\n", encoding="utf-8")
    _git(target, ["add", "branch-only.txt"])
    _git(target, ["commit", "-m", "selected checkout commit"])
    _git(project, ["commit", "--allow-empty", "-m", "independent main commit"])
    return target


@pytest.mark.parametrize("checkout", ["main", "branch", "detached"])
def test_workspace_write_starts_from_selected_checkout_and_reuses_receipt(project, tmp_path, checkout):
    target = project if checkout == "main" else linked_checkout(
        project, tmp_path / "selected checkout", detached=checkout == "detached",
    )
    expected_head = _git(target, ["rev-parse", "HEAD"]).strip()
    main_head = _git(project, ["rev-parse", "HEAD"]).strip()
    if checkout != "main":
        assert expected_head != main_head
    (target / "uncommitted.txt").write_text("leave in the source checkout", encoding="utf-8")
    source_status = _git(target, ["status", "--porcelain", "--", "uncommitted.txt"])

    runtime = FakeRuntime()
    dependencies = _service(tmp_path / "external", runtime).dependencies

    def service(**kwargs):
        return LocalAssistantTaskService(
            ExternalAgentTaskStore(tmp_path / "local"), project_root=target,
            dependencies=dependencies, authority_fingerprint=lambda: "a" * 64, **kwargs,
        )

    first_service = service()
    first = start(first_service)
    assert first["status"] == "running"
    record = first_service.store.get_task(first["taskId"])
    slug = "assistant-" + first["taskId"]
    workspace = Path(record["localWorkspacePath"])
    assert workspace == project / ".worktrees" / slug
    assert _git(workspace, ["rev-parse", "HEAD"]).strip() == expected_head
    assert (workspace / "branch-only.txt").exists() == (checkout != "main")
    assert not (workspace / "uncommitted.txt").exists()
    assert _git(target, ["status", "--porcelain", "--", "uncommitted.txt"]) == source_status
    assert _git(project, ["rev-parse", "HEAD"]).strip() == main_head
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1

    # A retry after the selected checkout advances still returns the durable
    # receipt and leaves the original task checkout and native turn intact.
    _git(target, ["commit", "--allow-empty", "-m", "another source commit"])

    def unexpected_workspace(task_id):
        pytest.fail(f"Retry tried to provision another workspace for {task_id}")

    retry_service = service(workspace_factory=unexpected_workspace)
    repeated = start(retry_service)
    assert repeated["taskId"] == first["taskId"]
    assert retry_service.store.get_task(first["taskId"]) == record
    assert _git(workspace, ["rev-parse", "HEAD"]).strip() == expected_head
    worktrees = _git(project, ["worktree", "list", "--porcelain"])
    assert worktrees.count(f"branch refs/heads/codex/{slug}\n") == 1
    assert len(runtime.create_calls) == len(runtime.submit_calls) == 1


def test_development_team_worktree_still_starts_from_main(project, tmp_path):
    target = linked_checkout(project, tmp_path / "selected checkout")
    main_head = _git(project, ["rev-parse", "main"]).strip()

    workspace = ensure_dev_task_workspace(
        team_id="team-1", task_id="task-1", member_id="member-1", project_root=target,
    )

    directory = project / workspace["workspacePath"]
    assert _git(directory, ["rev-parse", "HEAD"]).strip() == main_head
    assert not (directory / "branch-only.txt").exists()
