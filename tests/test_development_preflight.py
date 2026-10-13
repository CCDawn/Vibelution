from pathlib import Path
from types import SimpleNamespace
import os
import subprocess

import pytest

from scripts import development_preflight as preflight


@pytest.fixture
def instance(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    return {"id": "worktree:task", "kind": "worktree", "branch": "codex/task",
            "path": str(root), "checkedOut": True, "alive": False, "port": 8005}


@pytest.mark.parametrize("operation", ["start", "stop", "restart"])
def test_main_cannot_prepare_lifecycle(instance, operation):
    instance.update(id="main", kind="main", branch="main")
    with pytest.raises(ValueError):
        preflight.select_instance({"items": [instance]}, "main", operation)


@pytest.mark.parametrize("change", [
    {"checkedOut": False}, {"kind": "local_branch"}, {"kind": "retired"},
    {"branch": "detached"}, {"branch": "main"}, {"path": "/missing/checkout"},
])
def test_requires_an_isolated_registered_checkout(instance, change):
    instance.update(change)
    with pytest.raises(ValueError):
        preflight.select_instance({"items": [instance]}, "worktree:task", "restart")


@pytest.mark.parametrize("operation", ["force-stop", "rebuild-and-start", "powershell", "restart; stop"])
def test_arbitrary_operations_rejected(instance, operation):
    with pytest.raises(ValueError):
        preflight.select_instance({"items": [instance]}, "worktree:task", operation)


def test_missing_or_duplicate_instance_rejected(instance):
    for items in ([], [instance, instance]):
        with pytest.raises(ValueError):
            preflight.select_instance({"items": items}, "worktree:task", "restart")


@pytest.mark.parametrize("name", ["../secret", "a/../../secret", "C:/secret", "/secret", "\\\\host\\share", ".", ""])
def test_file_scope_cannot_escape_checkout(name):
    with pytest.raises(ValueError):
        preflight.normalize_files([name])


def test_report_does_not_authorize_dispatch_or_claim_runtime_passed(instance, tmp_path, monkeypatch):
    root = Path(instance["path"])
    layout = SimpleNamespace(integration_root=tmp_path, worktree_root=root)
    monkeypatch.setattr(preflight, "resolve_branch_workspace", lambda _: layout)
    monkeypatch.setattr(preflight, "list_branch_instances", lambda _: {"items": [instance]})
    calls = []

    def git(checkout, *args):
        calls.append((checkout, args))
        return "codex/task" if args[0] == "branch" else "a" * 40

    monkeypatch.setattr(preflight, "_git", git)
    monkeypatch.setattr(preflight.tempfile, "gettempdir", lambda: str(tmp_path / "scratch"))
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    report = preflight.build_report(tmp_path, "worktree:task", "restart", ["web/src/test.ts"])
    assert report["readOnly"] and not report["executionAttempted"]
    assert not report["approval"]["approvalGranted"]
    assert not report["runtime"]["runningRevisionVerified"]
    assert not report["runtime"]["browserAcceptanceVerified"]
    assert report["verification"]["refreshHint"] == "before_browser_acceptance"
    assert report["lifecycleHandoff"]["requiresHostApproval"]
    assert report["lifecycleHandoff"]["request"]["init"]["body"] == {"instanceId": "worktree:task"}
    assert [args for _, args in calls] == [("branch", "--show-current"), ("rev-parse", "HEAD")]
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before


def test_target_identity_change_fails_closed(instance, tmp_path, monkeypatch):
    layout = SimpleNamespace(integration_root=tmp_path, worktree_root=Path(instance["path"]))
    monkeypatch.setattr(preflight, "resolve_branch_workspace", lambda _: layout)
    monkeypatch.setattr(preflight, "list_branch_instances", lambda _: {"items": [instance]})
    monkeypatch.setattr(preflight, "_git", lambda *args: "main")
    with pytest.raises(ValueError, match="branch changed"):
        preflight.build_report(tmp_path, "worktree:task", "restart", [])


@pytest.mark.parametrize("files,expected", [
    ([], "review_required"), (["docs/a.md", "tests/test_x.py"], "none"),
    (["core/agent.py", "web/src/a.ts"], "before_runtime_acceptance"),
    (["unknown.data"], "review_required"),
])
def test_refresh_hint_never_assumes_unknown_files_are_runtime_safe(files, expected):
    assert preflight.refresh_requirement(files) == expected


def test_failure_output_does_not_echo_input(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "build_report", lambda *args: (_ for _ in ()).throw(ValueError("sensitive")))
    assert preflight.main(["--instance-id", "sensitive"]) == 2
    assert "sensitive" not in capsys.readouterr().out


def test_real_git_identity_and_registry_are_read_only(tmp_path, monkeypatch):
    # Test-only author identity and Git environment must never reach the real repo.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    integration = tmp_path / "repo"
    integration.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(integration), *args], check=True,
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    git("-c", "init.templateDir=", "init", "--initial-branch=main")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "core.hooksPath=", "commit", "--allow-empty", "-m", "fixture")
    task = integration / ".worktrees" / "test-task"
    git("worktree", "add", str(task), "-b", "codex/test-task")
    # Isolate product data discovery; all instance identities still come from real Git.
    from core.infrastructure import branch_workspace
    monkeypatch.setattr(branch_workspace, "_runtime_observation", lambda _: {})
    before = sorted(str(path) for path in integration.rglob("*"))
    report = preflight.build_report(task, "worktree:test-task", "restart", ["new.py"])
    assert report["target"]["branch"] == "codex/test-task"
    assert len(report["target"]["head"]) == 40
    assert report["development"]["isolationSatisfied"]
    assert not report["executionAttempted"]
    assert sorted(str(path) for path in integration.rglob("*")) == before
    main_report = preflight.build_report(integration, "main", "status", [])
    assert not main_report["development"]["isolationSatisfied"]
    assert main_report["development"]["suggestedWritableRoots"] == []
