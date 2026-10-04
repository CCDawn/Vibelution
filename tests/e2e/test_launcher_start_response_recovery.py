"""Real task startup with an injected lost response; never starts a model turn."""
from pathlib import Path

import pytest

from tests.e2e import conftest
from tests.e2e.helpers import ensure_web_build, instance_registry, launcher

pytestmark = [
    pytest.mark.serial,
    pytest.mark.skipif(not conftest.e2e_enabled(), reason="Set VIBELUTION_E2E=1 for isolated lifecycle acceptance"),
]


def test_started_task_is_cleaned_when_the_start_response_is_lost(monkeypatch):
    root = conftest.WORKTREE_ROOT
    ensure_web_build.ensure_web_build(root)
    monkeypatch.setenv("VIBELUTION_E2E_ATTACH", "0")
    monkeypatch.setenv("VIBELUTION_E2E_KEEP_DATA", "0")
    original_start = launcher.start_instance
    failure = launcher.LauncherCommandError("injected lost response after confirmed task startup")
    starts, observed = [], {}

    def lose_response(project_root):
        starts.append(project_root)
        original_start(project_root, hidden_presentation=True)
        entry = instance_registry.wait_for_entry(
            root, instance_registry.entry_is_ready, timeout_seconds=200,
            what="真实启动就绪后注入响应丢失",
        )
        data_home = conftest._resolve_data_home(entry)
        health = instance_registry.fetch_health(int(entry["port"]))
        instance_registry.assert_health_serves_worktree(health, root, data_home=data_home)
        observed.update(entry=entry, data_home=data_home)
        raise failure

    monkeypatch.setattr(launcher, "start_instance", lose_response)
    try:
        with pytest.raises(launcher.LauncherCommandError) as caught:
            conftest._start_or_attach_instance()
        assert caught.value is failure, "Preserve the original startup failure"
        assert starts == [root], "A lost response must never issue another start"
        assert observed, "The failure must be injected after real workspace readiness"
        _, entry = instance_registry.find_entry(root)
        assert instance_registry.entry_is_closed(entry)
        assert not any(entry.get(key) for key in ("spawnPid", "backendPid", "controlPid"))
        assert not Path(observed["data_home"]).exists()
    finally:
        # Also keep a RED run from orphaning the instance it demonstrably started.
        if observed:
            _, entry = instance_registry.find_entry(root)
            if not instance_registry.entry_is_closed(entry):
                port = int(entry["port"])
                conftest._teardown_instance(conftest.E2EInstance(
                    port=port, base_url=f"http://127.0.0.1:{port}",
                    instance_id=str(entry.get("instanceId") or ""), project_root=root,
                    data_home=observed["data_home"],
                ))
