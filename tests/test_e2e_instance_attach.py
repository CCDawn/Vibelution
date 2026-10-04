"""Explicit fixture recovery never retries lifecycle or adopts another tree."""
import pytest

from tests.e2e import conftest
from tests.e2e.helpers import instance_registry, launcher, launcher_ipc


@pytest.fixture(autouse=True)
def isolate_fixture_lifecycle(monkeypatch):
    monkeypatch.setattr(launcher_ipc, "_task_root", lambda root: root)
    monkeypatch.setattr(instance_registry, "load_registry", lambda: {"instances": {}})
    monkeypatch.setattr(conftest, "_resolve_data_home", lambda entry: "fixture-data")


@pytest.mark.parametrize("baseline_generation", [0, 3])
def test_failed_start_response_cleans_its_fresh_instance_and_preserves_failure(monkeypatch, baseline_generation):
    monkeypatch.delenv("VIBELUTION_E2E_ATTACH", raising=False)
    registry = {"instances": {}}
    if baseline_generation:
        registry["instances"]["task"] = {
            "projectRoot": str(conftest.WORKTREE_ROOT), "generation": baseline_generation,
            "commandId": "previous-command", "desiredState": "closed", "status": "closed",
        }
    monkeypatch.setattr(instance_registry, "load_registry", lambda: registry)
    error = launcher.LauncherCommandError("response lost after startup")

    def start(root):
        registry["instances"]["task"] = {
            "projectRoot": str(root), "generation": baseline_generation + 1, "commandId": "fresh-command",
            "desiredState": "open", "status": "starting", "port": 8002,
        }
        raise error

    stopped = []
    monkeypatch.setattr(launcher, "start_instance", start)
    monkeypatch.setattr(conftest, "_teardown_instance", stopped.append)
    with pytest.raises(launcher.LauncherCommandError) as caught:
        conftest._start_or_attach_instance()
    assert caught.value is error
    assert len(stopped) == 1
    assert stopped[0].project_root == conftest.WORKTREE_ROOT


@pytest.mark.parametrize("entry", [
    {"generation": 3, "commandId": "old"},
    {"generation": 3, "commandId": "new"},
    {"generation": 4, "commandId": "old"},
    {"generation": 4, "commandId": ""},
    {"generation": 4, "commandId": "new", "projectRoot": "C:/another-task"},
    {"generation": 4, "commandId": "new", "projectRoot": ""},
])
def test_start_failure_never_cleans_an_unproven_instance(monkeypatch, entry):
    monkeypatch.delenv("VIBELUTION_E2E_ATTACH", raising=False)
    baseline = {"projectRoot": str(conftest.WORKTREE_ROOT), "generation": 3,
                "commandId": "old", "desiredState": "closed", "status": "closed"}
    registry = {"instances": {"task": baseline}}
    monkeypatch.setattr(instance_registry, "load_registry", lambda: registry)
    error = launcher.LauncherCommandError("no confirmed new instance")

    def start(root):
        registry["instances"]["task"] = {"projectRoot": str(root), **entry}
        raise error

    stopped = []
    monkeypatch.setattr(launcher, "start_instance", start)
    monkeypatch.setattr(conftest, "_teardown_instance", stopped.append)
    with pytest.raises(launcher.LauncherCommandError) as caught:
        conftest._start_or_attach_instance()
    assert caught.value is error
    assert stopped == []


def test_default_start_rejects_an_existing_active_instance(monkeypatch):
    monkeypatch.delenv("VIBELUTION_E2E_ATTACH", raising=False)
    entry = {"projectRoot": str(conftest.WORKTREE_ROOT), "desiredState": "open", "status": "steady"}
    monkeypatch.setattr(instance_registry, "load_registry", lambda: {"instances": {"task": entry}})
    monkeypatch.setattr(launcher, "start_instance", lambda root: pytest.fail("duplicate start"))
    with pytest.raises(launcher.LauncherCommandError, match="尚未关闭"):
        conftest._start_or_attach_instance()


def test_cleanup_failure_does_not_replace_the_start_error(monkeypatch, capsys):
    monkeypatch.delenv("VIBELUTION_E2E_ATTACH", raising=False)
    registry = {"instances": {}}
    monkeypatch.setattr(instance_registry, "load_registry", lambda: registry)
    error = launcher.LauncherCommandError("original startup failure")

    def start(root):
        registry["instances"]["task"] = {"projectRoot": str(root), "generation": 1, "commandId": "fresh"}
        raise error

    def blocked(instance):
        raise launcher.LauncherCommandError("stop refused by active work guard")

    monkeypatch.setattr(launcher, "start_instance", start)
    monkeypatch.setattr(conftest, "_teardown_instance", blocked)
    with pytest.raises(launcher.LauncherCommandError) as caught:
        conftest._start_or_attach_instance()
    assert caught.value is error
    assert "清理未闭环" in capsys.readouterr().out


def test_default_fixture_starts_normally(monkeypatch):
    monkeypatch.delenv("VIBELUTION_E2E_ATTACH", raising=False)
    calls = []
    monkeypatch.setattr(launcher, "start_instance", calls.append)
    conftest._start_or_attach_instance()
    assert calls == [conftest.WORKTREE_ROOT]


def test_explicit_attach_checks_task_identity_and_does_not_start(monkeypatch):
    monkeypatch.setenv("VIBELUTION_E2E_ATTACH", "1")
    monkeypatch.setattr(launcher, "start_instance", lambda root: pytest.fail("duplicate start"))
    checked = []
    monkeypatch.setattr(launcher_ipc, "_task_root", checked.append)
    entry = {"desiredState": "open", "status": "steady", "phase": "steady", "spawnPid": 1, "portLeaseStatus": "held"}
    monkeypatch.setattr(instance_registry, "find_entry", lambda root: ("task", entry))
    conftest._start_or_attach_instance()
    assert checked == [conftest.WORKTREE_ROOT]


@pytest.mark.parametrize("entry", [None, {"desiredState": "open", "status": "starting"}])
def test_attach_rejects_missing_or_not_ready_without_start(monkeypatch, entry):
    monkeypatch.setenv("VIBELUTION_E2E_ATTACH", "1")
    monkeypatch.setattr(launcher, "start_instance", lambda root: pytest.fail("unexpected start"))
    monkeypatch.setattr(launcher_ipc, "_task_root", lambda root: root)

    def find(root):
        if entry is None:
            raise instance_registry.InstanceRegistryError("missing")
        return "task", entry

    monkeypatch.setattr(instance_registry, "find_entry", find)
    with pytest.raises(instance_registry.InstanceRegistryError):
        conftest._start_or_attach_instance()


def test_attach_rejects_wrong_tree_before_reading_registry(monkeypatch):
    monkeypatch.setenv("VIBELUTION_E2E_ATTACH", "1")
    monkeypatch.setattr(launcher, "start_instance", lambda root: pytest.fail("unexpected start"))

    def reject(root):
        raise launcher.LauncherCommandError("wrong task")

    monkeypatch.setattr(launcher_ipc, "_task_root", reject)
    monkeypatch.setattr(instance_registry, "find_entry", lambda root: pytest.fail("registry lookup"))
    with pytest.raises(launcher.LauncherCommandError, match="wrong task"):
        conftest._start_or_attach_instance()


def test_attach_rejects_invalid_flag(monkeypatch):
    monkeypatch.setenv("VIBELUTION_E2E_ATTACH", "invalid")
    monkeypatch.setattr(launcher, "start_instance", lambda root: pytest.fail("unexpected start"))
    with pytest.raises(instance_registry.InstanceRegistryError, match="0 或 1"):
        conftest._start_or_attach_instance()
