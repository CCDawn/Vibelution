"""Migration CLI keeps the old read path and makes every target write explicit."""
import json
from types import SimpleNamespace

import pytest

import scripts.assistant_migration_inventory as cli
from tests.test_assistant_migration_history import AGENT, source


def fixture(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root: SimpleNamespace(
        project_root=workspace.parent, data=workspace.parent, project_id="p", instance_id="i",
        runtime=tmp_path / "runtime"))
    return workspace


def call(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["inventory", "--project", "C:/selected-project", *map(str, args)])
    return cli.main()


def test_cli_imports_all_retained_history_into_only_the_explicit_target(tmp_path, monkeypatch, capsys):
    workspace = fixture(tmp_path, monkeypatch)
    target = tmp_path / "target"
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert call(monkeypatch, "--history-preview", AGENT) == 0
    assert json.loads(capsys.readouterr().out)["historyComplete"]
    assert call(monkeypatch, "--history-import", AGENT, "--target-profile", target, "--migration-id", "migration-1") == 0
    assert json.loads(capsys.readouterr().out)["import"]["published"]
    assert before == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert list(target.rglob("manifest.json"))


def test_source_path_grants_and_import_preserve_exact_external_bytes(tmp_path, monkeypatch, capsys):
    workspace = fixture(tmp_path, monkeypatch)
    external = tmp_path / "external-memory"
    external.mkdir()
    body = b'{"text":"PRIVATE_MEMORY"}\n'
    (external / "memory.jsonl").write_bytes(body)
    registry = workspace / "agents/agents.json"
    document = json.loads(registry.read_bytes())
    document["agents"][0]["memoryPolicy"] = {"privateMemoryRoot": str(external)}
    registry.write_text(json.dumps(document), encoding="utf-8")
    grant = tmp_path / "grants.json"
    grant.write_text(json.dumps({"schemaVersion": 1, "sourceScope": {"projectId": "p", "instanceId": "i", "agentId": AGENT},
        "grants": [{"category": "memory", "root": str(external), "revision": 1}]}), encoding="utf-8")
    assert call(monkeypatch, "--source-import", AGENT, "--path-grants", grant,
                "--target-profile", tmp_path / "target", "--migration-id", "source-1") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["import"]["published"] and result["readyForCutover"] is False
    assert "PRIVATE_MEMORY" not in json.dumps(result)
    assert next((tmp_path / "target").rglob("memory.jsonl")).read_bytes() == body


@pytest.mark.parametrize("args", [("--history-import", AGENT), ("--target-profile", "C:/target"),
    ("--source-paths", AGENT, "--request-id", "bad"), ("--observe-handoff", AGENT)])
def test_incomplete_or_ambiguous_write_intent_is_rejected_before_any_storage_lookup(monkeypatch, args):
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda *_: pytest.fail("source lookup before validation"))
    with pytest.raises(SystemExit) as error:
        call(monkeypatch, *args)
    assert error.value.code == 2


def test_bad_registry_is_a_bounded_failure_not_traceback(tmp_path, monkeypatch, capsys):
    workspace = fixture(tmp_path, monkeypatch)
    (workspace / "agents/agents.json").write_bytes(b'[]')
    assert call(monkeypatch, "--source-paths", AGENT) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_source_registry"


def test_observer_cli_shares_native_credential_owner_and_refuses_busy_profile(tmp_path, monkeypatch, capsys):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from core.assistant_runtime.dispatch import DispatchService
    from core.infrastructure.file_lock import cross_process_file_lock
    workspace = fixture(tmp_path, monkeypatch)
    config = observer_route(tmp_path, monkeypatch, workspace)
    target = tmp_path / "target"
    target.mkdir()
    calls = []
    async def blocked(*args, **kwargs):
        calls.append(args)
        pytest.fail("busy profile reached SDK")
    monkeypatch.setattr(DispatchService, "_call", blocked)
    release, locked = threading.Event(), threading.Event()
    def owner():
        with cross_process_file_lock(target / "host-owner"):
            locked.set()
            assert release.wait(10)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner)
        try:
            assert locked.wait(5)
            assert call(monkeypatch, "--observe-handoff", AGENT, "--target-profile", target,
                "--source-config", config,
                "--registered-project-id", "registered-project", "--request-id", "observe-1",
                "--message-id", "dispatch") == 1
            assert json.loads(capsys.readouterr().out)["code"] == "TARGET_PROFILE_BUSY"
            assert calls == []
        finally:
            release.set()
            future.result(timeout=5)


def test_observer_cli_uses_registered_project_and_original_sdk_state(tmp_path, monkeypatch, capsys):
    import hashlib
    from core.assistant_runtime.dispatch import DispatchService
    workspace = fixture(tmp_path, monkeypatch)
    config = observer_route(tmp_path, monkeypatch, workspace)
    target = tmp_path / "target"
    target.mkdir()
    seen = []
    class Client:
        async def management_legacy_observer_create(self, **kwargs):
            seen.append(kwargs)
            return {"status": "created", "actions": ["read_receipt"]}
    async def call_sdk(self, project_id, operation):
        assert project_id == "registered-project"
        assert self._root == target / "assistant_dispatch"
        assert list(self._projects) == ["registered-project"]
        return await operation(Client())
    monkeypatch.setattr(DispatchService, "_call", call_sdk)
    assert call(monkeypatch, "--observe-handoff", AGENT, "--target-profile", target,
        "--source-config", config,
        "--registered-project-id", "registered-project", "--request-id", "observe-1",
        "--message-id", "b", "--message-id", "a", "--message-id", "b") == 0
    assert json.loads(capsys.readouterr().out)["actions"] == ["read_receipt"]
    assert seen == [{"request_id": "observe-1", "source_agent_id": AGENT,
        "legacy_message_ids": ["a", "b"],
        "expected_registry_sha256": hashlib.sha256((workspace / "agents/agents.json").read_bytes()).hexdigest(),
        "expected_source_authority": "a" * 64}]


def observer_route(tmp_path, monkeypatch, workspace):
    from core.infrastructure import developer_sandbox
    from core.web.services.external_management.legacy_native import LegacyNativeGateway
    config = tmp_path / "source-config.toml"
    config.write_text("[launcher.developer_mode]\nenabled=false\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda _root, *parts: workspace.joinpath(*parts))
    monkeypatch.setattr(LegacyNativeGateway, "snapshot", lambda *args: SimpleNamespace(
        data={"sourceAuthority": "a" * 64}, verify=lambda: None))
    return config


def test_explicit_existing_source_config_imports_sandbox_without_formal_read_or_repair(tmp_path, monkeypatch, capsys):
    from core.infrastructure import developer_sandbox
    from core.assistant_runtime.migration_history import list_history
    formal = fixture(tmp_path, monkeypatch)
    (formal / "agents/agents.json").write_bytes(b"INVALID_FORMAL_REGISTRY")
    sandbox = source(tmp_path / "sandbox")
    config = tmp_path / "sandbox-config.toml"
    config.write_text("[launcher.developer_mode]\nenabled=true\n", encoding="utf-8")
    active = tmp_path / "active-sandbox.json"
    active.write_text('{"schemaVersion":1,"sandboxId":"source"}', encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "_active_state_path", lambda root: active)
    monkeypatch.setattr(developer_sandbox, "_sandbox_root", lambda root, token: sandbox.parent)
    before = {p: p.read_bytes() for p in sandbox.rglob("*") if p.is_file()}
    target = tmp_path / "target"
    assert call(monkeypatch, "--history-import", AGENT, "--source-config", config,
        "--target-profile", target, "--migration-id", "sandbox-history") == 0
    assert json.loads(capsys.readouterr().out)["import"]["published"]
    assert len(list_history(target)) == 1
    assert before == {p: p.read_bytes() for p in sandbox.rglob("*") if p.is_file()}
    assert (formal / "agents/agents.json").read_bytes() == b"INVALID_FORMAL_REGISTRY"


def test_observer_source_route_change_refuses_before_native_grant_creation(tmp_path, monkeypatch, capsys):
    from core.assistant_runtime.dispatch import DispatchService
    from core.web.services.external_management.legacy_native import LegacyNativeGateway
    workspace = fixture(tmp_path, monkeypatch)
    config = observer_route(tmp_path, monkeypatch, workspace)
    target = tmp_path / "target"
    target.mkdir()
    def route_changed(*args):
        config.write_text("[launcher.developer_mode]\nenabled=false\n# changed\n", encoding="utf-8")
        return SimpleNamespace(data={"sourceAuthority": "b" * 64}, verify=lambda: None)
    monkeypatch.setattr(LegacyNativeGateway, "snapshot", route_changed)
    async def unexpected(*args):
        pytest.fail("changed source reached native grant creation")
    monkeypatch.setattr(DispatchService, "_call", unexpected)
    assert call(monkeypatch, "--observe-handoff", AGENT, "--source-config", config,
        "--target-profile", target, "--registered-project-id", "registered-project",
        "--request-id", "observe-1", "--message-id", "dispatch") == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SOURCE_MIGRATION_UNAVAILABLE"
