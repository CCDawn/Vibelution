"""Explicit fixture recovery never retries lifecycle or adopts another tree."""
import pytest

from tests.e2e import conftest
from tests.e2e.helpers import instance_registry, launcher, launcher_ipc


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
