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


def test_recovery_disposition_cli_only_observes_the_selected_source(tmp_path, monkeypatch, capsys):
    from tests.test_assistant_migration_recovery_bindings import source as recovery_source
    workspace, _, _ = recovery_source(tmp_path)
    registry = workspace / "agents/agents.json"
    registry.write_text(json.dumps({"agents": [{"agentId": "assistant", "directSessionId": "session-1",
        "roleKey": "personal_assistant", "status": "active", "workspacePath": "workspace/agents/assistant",
        "metadata": {"personalAssistantProfile": "personal_assistant_v1"}}]}), encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root: SimpleNamespace(
        project_root=tmp_path, data=tmp_path, project_id="project", instance_id="instance", runtime=tmp_path / "runtime"))
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert call(monkeypatch, "--recovery-inventory", "assistant") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == "recovery_inventory" and result["inventoryComplete"]
    assert len(result["bindings"]) == 2 and result["readyForCutover"] is False
    assert all(row["requires_native_reauthorization"] for row in result["bindings"])
    assert "PRIVATE_" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)
    assert before == {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}


def test_recovery_cli_does_not_infer_grants_from_stale_canonical_path(tmp_path, monkeypatch, capsys):
    from tests.test_assistant_migration_recovery_bindings import source as recovery_source
    workspace, _, canonical = recovery_source(tmp_path)
    canonical.write_text("STALE_NOT_JSON", encoding="utf-8")
    registry = workspace / "agents/agents.json"
    registry.write_text(json.dumps({"agents": [{"agentId": "assistant", "directSessionId": "session-1",
        "roleKey": "personal_assistant", "status": "active", "workspacePath": "workspace/agents/custom",
        "metadata": {"personalAssistantProfile": "personal_assistant_v1"}}]}), encoding="utf-8")
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root: SimpleNamespace(
        project_root=tmp_path, data=tmp_path, project_id="project", instance_id="instance", runtime=tmp_path / "runtime"))
    assert call(monkeypatch, "--recovery-inventory", "assistant") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["inventoryComplete"] is False
    assert report["temporaryGrants"]["status"] == "unresolved"
    assert report["temporaryGrants"]["reason"] == "explicit_governance_path_authorization_required"


def active_personal_case(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG
    workspace = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(developer_sandbox, "formal_workspace_path", lambda _root, *parts: workspace.joinpath(*parts))
    episode = {"schemaVersion": 1, "episodeId": "old-episode", "eventId": "old-episode", "agentId": AGENT,
        "kind": "preference", "text": "Synthetic preference", "refs": [], "occurredAt": "2025-01-01T00:00:00+00:00",
        "validFrom": "2025-01-01T00:00:00+00:00", "validUntil": "", "supersededByEpisodeId": ""}
    affair = {"schemaVersion": 1, "itemId": "old-todo", "kind": "todo", "title": "Synthetic task",
        "note": "", "status": "open", "dueAt": "", "createdAt": "2025-01-01T00:00:00+00:00",
        "updatedAt": "2025-01-01T00:00:00+00:00", "completedAt": "", "sourceTurnId": ""}
    events = workspace / 'agents' / AGENT / 'events/episodic_events.jsonl'
    events.parent.mkdir(parents=True)
    events.write_text(json.dumps(episode) + '\n', encoding='utf-8')
    ledger = workspace / 'agents' / AGENT / 'plugins/personal-affairs/affairs/items.jsonl'
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(affair) + '\n', encoding='utf-8')
    source_config = tmp_path / 'source-config.toml'
    source_config.write_text('[launcher.developer_mode]\nenabled=false\n', encoding='utf-8')
    target = tmp_path / 'native'
    target_config = target / 'config/config.toml'
    target_config.parent.mkdir(parents=True)
    target_config.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    args = ('--activate-personal', AGENT, '--source-config', source_config, '--target-profile', target,
            '--target-config', target_config, '--migration-id', 'cli-activation')
    return workspace, target, args


def test_active_personal_cli_imports_in_isolated_native_process_and_recovers(tmp_path, monkeypatch, capsys):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    assert call(monkeypatch, *args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['status'] == 'complete' and not first['readyForCutover']
    assert first['episodic']['importedCount'] == 1 and first['affairs']['importedCount'] == 1
    assert call(monkeypatch, *args) == 0
    retry = json.loads(capsys.readouterr().out)
    assert retry['episodic']['idempotent'] and retry['affairs']['idempotent']
    assert before == {p: p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    _run(tmp_path, '''
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import personal_affairs_service
        from core.web.services.agent_directory import episodic_memory
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            aid = native.bootstrap(root)['assistant']['agentId']
            assert [row['episodeId'] for row in episodic_memory.list_episodic_events(aid)] == ['old-episode']
            assert personal_affairs_service.get_personal_affairs_service().list_items(aid)['items'][0]['itemId'] == 'old-todo'
        finally:
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("config_mode", ["outside", "missing"])
def test_activation_requires_existing_config_inside_target_before_spawn(tmp_path, monkeypatch, capsys, config_mode):
    import subprocess
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    config = tmp_path / "outside-config.toml" if config_mode == "outside" else target / "missing.toml"
    if config_mode == "outside":
        config.write_text("", encoding="utf-8")
    options = list(args)
    options[options.index("--target-config") + 1] = config
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("invalid target reached child"))
    assert call(monkeypatch, *options) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SOURCE_MIGRATION_UNAVAILABLE"
    assert list(target.iterdir()) == [target / "config"]


def test_activation_child_rejects_changed_source_proof_before_native_bootstrap(tmp_path, monkeypatch, capsys):
    import subprocess
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    real_run = subprocess.run
    def changed_source(*positional, **kwargs):
        registry = workspace / "agents/agents.json"
        registry.write_bytes(registry.read_bytes() + b"\n")
        process = real_run(*positional, **kwargs)
        assert process.returncode == 1
        assert json.loads(process.stdout)["reason"] == "source_authority_changed"
        assert list(target.iterdir()) == [target / "config"]
        return process
    monkeypatch.setattr(subprocess, "run", changed_source)
    assert call(monkeypatch, *args) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SOURCE_MIGRATION_UNAVAILABLE"


@pytest.mark.parametrize("failure", ["missing_receipt", "timeout"])
def test_activation_unknown_outcome_is_not_automatically_replayed(tmp_path, monkeypatch, capsys, failure):
    import subprocess
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    calls = []
    def uncertain(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] is False
        assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        assert command[1:3] == ["-I", "-B"]
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="", stderr="private child diagnostic")
    monkeypatch.setattr(subprocess, "run", uncertain)
    assert call(monkeypatch, *args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "activation_outcome_unknown" and len(calls) == 1
    assert "private" not in json.dumps(result)


def test_activation_real_child_denies_network_process_escape_and_source_writes(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from scripts import assistant_migration_activate as activation
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    config = target / "config/config.toml"
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VIBELUTION_SECRET", "PYTHONPATH", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "must-not-be-inherited")
    env = activation._isolated_environment(target, config)
    assert not any("API_KEY" in key or "SECRET" in key for key in env)
    code = r'''
import os, sys, socket, subprocess
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.assistant_migration_activate import _install_audit
target, source = Path(sys.argv[2]), Path(sys.argv[3])
_install_audit(target)
for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP', 'TMPDIR'):
    assert Path(os.environ[key]).is_relative_to(target)
for operation in (
    lambda: source.write_text('changed'),
    lambda: source.parent.joinpath('unexpected').mkdir(),
    lambda: socket.socket().connect(('127.0.0.1', 9)),
    lambda: subprocess.run([sys.executable, '-c', 'pass']),
):
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('offline isolation escape')
(target / 'allowed.txt').write_text('allowed')
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(activation.ROOT), str(target),
        str(workspace / "agents/agents.json")], env=env, capture_output=True,
        text=True, encoding="utf-8", shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
    assert result.returncode == 0, result.stderr
    assert (target / "allowed.txt").read_text() == "allowed"
    assert not (workspace / "agents/unexpected").exists()


def test_activation_keeps_confirmed_native_commit_when_child_final_source_check_fails(tmp_path, monkeypatch, capsys):
    import subprocess
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    real_run = subprocess.run
    code = r'''
import sys
sys.path.insert(0, sys.argv[1])
from scripts import assistant_migration_activate as cli
from core.assistant_runtime import migration_active, migration_affairs
from core.assistant_runtime.migration_io import MigrationIOError
original_activate, original_verify = migration_active.activate_personal_snapshot, cli._verify_file_proofs
finished = False
def fail_second_category(*args, **kwargs):
    raise MigrationIOError('source_changed')
def activate(*args, **kwargs):
    global finished
    result = original_activate(*args, **kwargs)
    finished = True
    return result
def final_source_change(proofs):
    if finished: raise MigrationIOError('source_authority_changed')
    return original_verify(proofs)
migration_affairs.import_affairs = fail_second_category
migration_active.activate_personal_snapshot = activate
cli._verify_file_proofs = final_source_change
raise SystemExit(cli._child())
'''
    def child_with_failure(command, **kwargs):
        return real_run([command[0], "-I", "-B", "-c", code, str(cli.ROOT)], **kwargs)
    monkeypatch.setattr(subprocess, "run", child_with_failure)
    assert call(monkeypatch, *args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "partial" and result["migrationId"] == "cli-activation"
    assert result["episodic"]["importedCount"] == 1 and "affairs" not in result
    assert result["failedCategory"] == "affairs" and result["reason"] == "source_changed"
    assert result["requiresReconciliation"] and result["sourceValidation"] == "changed"
    assert not result["readyForCutover"]
    assert list((target / "episodic_migrations").rglob("*.json"))


def test_activation_keeps_receipts_when_source_changes_after_child_returns(tmp_path, monkeypatch, capsys):
    import subprocess
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    real_run = subprocess.run
    calls = []
    def changed_source_after_commit(command, **kwargs):
        process = real_run(command, **kwargs)
        calls.append(command)
        assert json.loads(process.stdout)["status"] == "complete"
        config = args[args.index("--source-config") + 1]
        config.write_bytes(config.read_bytes() + b"\n# routing authority changed after commit\n")
        return process
    monkeypatch.setattr(subprocess, "run", changed_source_after_commit)
    assert call(monkeypatch, *args) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and result["status"] == "partial"
    assert result["episodic"]["importedCount"] == 1 and result["affairs"]["importedCount"] == 1
    assert result["migrationId"] == "cli-activation" and result["requiresReconciliation"]
    assert result["sourceValidation"] == "changed" and not result["readyForCutover"]


def test_non_activation_read_mode_still_fails_final_source_authority_check(tmp_path, monkeypatch, capsys):
    from core.assistant_runtime import migration_history
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    config = args[args.index("--source-config") + 1]
    def changed_read(**kwargs):
        config.write_bytes(config.read_bytes() + b"\n# changed during preview\n")
        return SimpleNamespace(report={"historyComplete": True})
    monkeypatch.setattr(migration_history, "discover_history", changed_read)
    assert call(monkeypatch, "--history-preview", AGENT, "--source-config", config) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SOURCE_MIGRATION_UNAVAILABLE"


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
