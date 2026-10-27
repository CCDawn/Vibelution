"""Migration CLI keeps the old read path and makes every target write explicit."""
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.assistant_migration_inventory as cli
from tests.test_assistant_migration_history import AGENT, source


def fixture(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root, **_kwargs: SimpleNamespace(
        project_root=workspace.parent, data=workspace.parent, project_id="p", instance_id="i",
        runtime=tmp_path / "runtime"))
    return workspace


def call(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["inventory", "--project", os.environ.get("TEST_MIGRATION_PROJECT", "C:/selected-project"), *map(str, args)])
    return cli.main()


def authorized_fixture(tmp_path, monkeypatch):
    from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path
    old_workspace = source(tmp_path)
    project = old_workspace.parent
    identity = project / '.vibelution/project.json'
    identity.parent.mkdir()
    identity.write_text(json.dumps({'schemaVersion': 1, 'projectId': 'test-project'}), encoding='utf-8')
    projects = tmp_path / 'source-projects'
    monkeypatch.delenv('VIBELUTION_DATA_HOME', raising=False)
    monkeypatch.setenv('VIBELUTION_PROJECTS_HOME', str(projects))
    monkeypatch.setenv('TEST_MIGRATION_PROJECT', str(project))
    paths = resolve_project_storage_paths(project, projects_home=projects)
    paths.workspace.parent.mkdir(parents=True)
    shutil.move(str(old_workspace), str(paths.workspace))
    marker = storage_migration_state_path(paths)
    marker.write_text(json.dumps({'schemaVersion': 1, 'status': 'completed',
        'projectId': paths.project_id, 'instanceId': paths.instance_id}), encoding='utf-8')
    return paths.workspace, paths


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
    workspace, paths = authorized_fixture(tmp_path, monkeypatch)
    external = tmp_path / "external-memory"
    external.mkdir()
    body = b'{"text":"PRIVATE_MEMORY"}\n'
    (external / "memory.jsonl").write_bytes(body)
    registry = workspace / "agents/agents.json"
    document = json.loads(registry.read_bytes())
    document["agents"][0]["memoryPolicy"] = {"privateMemoryRoot": str(external)}
    registry.write_text(json.dumps(document), encoding="utf-8")
    grant = tmp_path / "grants.json"
    grant.write_text(json.dumps({"schemaVersion": 1, "sourceScope": {"projectId": paths.project_id, "instanceId": paths.instance_id, "agentId": AGENT},
        "grants": [{"category": "memory", "root": str(external), "revision": 1}]}), encoding="utf-8")
    source_config = tmp_path / 'source-config.toml'
    source_config.write_text('[launcher.developer_mode]\nenabled=false\n', encoding='utf8')
    assert call(monkeypatch, "--source-import", AGENT, "--path-grants", grant,
                "--target-profile", tmp_path / "target", "--migration-id", "source-1", "--source-config", source_config) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["import"]["published"] and result["readyForCutover"] is False
    assert "PRIVATE_MEMORY" not in json.dumps(result)
    assert next((tmp_path / "target").rglob("memory.jsonl")).read_bytes() == body


@pytest.mark.parametrize("args", [("--history-import", AGENT), ("--target-profile", "C:/target"),
    ("--source-paths", AGENT, "--request-id", "bad"), ("--observe-handoff", AGENT),
    ("--prepare-affairs-conflicts", AGENT, "--target-profile", "C:/target", "--migration-id", "current"),
    ("--source-import", AGENT, "--target-profile", "C:/target", "--migration-id", "source"),
    ("--baseline-migration-id", "old")])
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
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root, **_kwargs: SimpleNamespace(
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
    monkeypatch.setattr(cli, "resolve_active_project_storage_paths", lambda root, **_kwargs: SimpleNamespace(
        project_root=tmp_path, data=tmp_path, project_id="project", instance_id="instance", runtime=tmp_path / "runtime"))
    assert call(monkeypatch, "--recovery-inventory", "assistant") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["inventoryComplete"] is False
    assert report["temporaryGrants"]["status"] == "unresolved"
    assert report["temporaryGrants"]["reason"] == "explicit_governance_path_authorization_required"


def test_active_knowledge_cli_imports_native_private_knowledge_and_restarts(tmp_path, monkeypatch, capsys):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
    workspace, _ = authorized_fixture(tmp_path, monkeypatch)
    (tmp_path / "source-location.json").write_text(json.dumps({"workspace": str(workspace)}), encoding="utf-8")
    _run(tmp_path, r'''
        import json, os, shutil, sys
        from pathlib import Path
        def no_network(event, args):
            if event == 'socket.connect': raise AssertionError('network forbidden')
        sys.addaudithook(no_network)
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import team_knowledge_service as knowledge, agent_directory_service as directory
        knowledge._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = Path(json.loads((root.parent / 'source-location.json').read_text())['workspace'])
        with offline_migration_profile() as lease:
            old = lease.agent_id
            base = knowledge.create_agent_knowledge_base(old, name='Synthetic', actor_agent_id=old)
            source = knowledge.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='SYNTHETIC_MIGRATED_KNOWLEDGE', title='Synthetic', actor_agent_id=old)
            knowledge.review_owner_inbox_source('agent', old, source['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True, knowledge_base_id=base['scopedKnowledgeBaseId'],
                knowledge_content='SYNTHETIC_MIGRATED_KNOWLEDGE')
            owner = knowledge._require_owner_context('agent', old)
            shutil.copytree(knowledge._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge')
            registry = workspace / 'knowledge/sources/registry'
            registry.mkdir(parents=True)
            shutil.copyfile(knowledge._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(knowledge._central_owner_refs_path(), registry / 'owner_refs.jsonl')
            row = {'agentId': old, 'directSessionId': lease.session_id, 'status': 'active',
                'roleKey': 'personal_assistant', 'metadata': {'personalAssistantProfile': 'personal_assistant_v1'}}
            (workspace / 'agents/agents.json').write_text(json.dumps({'agents': [row]}), encoding='utf-8')
            (root.parent / 'old-id.txt').write_text(old, encoding='utf-8')
    ''', config_text=TEST_MODEL_CONFIG)
    old_id = (tmp_path / 'old-id.txt').read_text(encoding='utf-8')
    source_config = tmp_path / 'source-config.toml'
    source_config.write_text('[launcher.developer_mode]\nenabled=false\n', encoding='utf-8')
    new_root = tmp_path / 'new-profile'
    new_root.mkdir()
    target = new_root / 'native'
    target_config = target / 'config/config.toml'
    target_config.parent.mkdir(parents=True)
    target_config.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    before = {p: p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    args = ('--activate-knowledge', old_id, '--source-config', source_config, '--target-profile', target,
            '--target-config', target_config, '--migration-id', 'knowledge-cli')
    # An uncertain child response must keep the original identity and never
    # dispatch a second import automatically.
    import subprocess
    requests = []
    with monkeypatch.context() as patcher:
        def timeout(command, **kwargs):
            requests.append(command)
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        patcher.setattr(subprocess, 'run', timeout)
        assert call(monkeypatch, *args) == 1
        uncertain = json.loads(capsys.readouterr().out)
    assert len(requests) == 1 and uncertain['migrationId'] == 'knowledge-cli'
    assert uncertain['outcomeUnknown'] and uncertain['requiresReconciliation']
    # A trusted result is retained if its source authority changes after the
    # child responds; it is not reported as a clean, complete activation.
    source_bytes = source_config.read_bytes()
    calls = []
    with monkeypatch.context() as patcher:
        def changed(command, **kwargs):
            request = json.loads(kwargs['input'])
            calls.append(request)
            source_config.write_bytes(source_bytes + b'\n# synthetic change\n')
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'status': 'complete', 'sourceScope': request['scope'],
                'migrationId': request['migrationId'], 'readyForCutover': False,
                'knowledge': {'importedCount': 1}}), stderr='')
        patcher.setattr(subprocess, 'run', changed)
        assert call(monkeypatch, *args) == 0
        partial = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and partial['status'] == 'partial'
    assert partial['requiresReconciliation'] and partial['knowledge']['importedCount'] == 1
    source_config.write_bytes(source_bytes)
    # Fail after a native KB has been created and its next intent persisted.
    # The CLI must report an unknown outcome without an automatic replay.
    import sys
    from scripts import assistant_migration_activate as activation
    broken = tmp_path / 'broken-profile/native'
    broken_config = broken / 'config/config.toml'
    broken_config.parent.mkdir(parents=True)
    broken_config.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    broken_args = ('--activate-knowledge', old_id, '--source-config', source_config,
        '--target-profile', broken, '--target-config', broken_config, '--migration-id', 'unknown-knowledge')
    real_run, calls = subprocess.run, []
    inject = r'''
import sys
sys.path.insert(0, sys.argv[1])
from scripts import assistant_migration_activate as entry
from core.assistant_runtime import migration_knowledge as knowledge
original = knowledge._write_state
def interrupted(path, state):
    original(path, state)
    if state.get('phase') == 'collect_intent': raise RuntimeError('synthetic lost acknowledgment')
knowledge._write_state = interrupted
raise SystemExit(entry._child())
'''
    with monkeypatch.context() as patcher:
        def interrupted(command, **kwargs):
            calls.append(command)
            return real_run([sys.executable, '-I', '-B', '-c', inject, str(activation.ROOT)], **kwargs)
        patcher.setattr(subprocess, 'run', interrupted)
        assert call(monkeypatch, *broken_args) == 1
        unknown = json.loads(capsys.readouterr().out)
    assert len(calls) == 1 and unknown['migrationId'] == 'unknown-knowledge'
    assert unknown['outcomeUnknown'] and unknown['requiresReconciliation']
    states = list((broken / 'knowledge_migrations').glob('*.json'))
    assert len(states) == 1 and json.loads(states[0].read_text(encoding='utf-8'))['phase'] == 'collect_intent'
    # While a real child is at the first native write boundary, another
    # process must be unable to change the source routing configuration.
    import time
    fenced = tmp_path / 'fenced-profile/native'
    fenced_config = fenced / 'config/config.toml'
    fenced_config.parent.mkdir(parents=True)
    fenced_config.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    fenced_args = ('--activate-knowledge', old_id, '--source-config', source_config,
        '--target-profile', fenced, '--target-config', fenced_config, '--migration-id', 'fenced-knowledge')
    fence_code = r'''
import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts import assistant_migration_activate as entry
from core.assistant_runtime import migration_knowledge as knowledge
original = knowledge._write_state
def pause(path, state):
    if state.get('phase') == 'base_intent':
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        (root / 'fence-ready').write_text('ready')
        deadline = time.monotonic() + 20
        while not (root / 'fence-continue').exists():
            if time.monotonic() >= deadline: raise RuntimeError('fence timeout')
            time.sleep(.02)
    return original(path, state)
knowledge._write_state = pause
raise SystemExit(entry._child())
'''
    with monkeypatch.context() as patcher:
        def fenced_child(command, **kwargs):
            options = {key: kwargs[key] for key in ('cwd', 'env', 'shell', 'creationflags', 'text', 'encoding')}
            with subprocess.Popen([sys.executable, '-I', '-B', '-c', fence_code, str(activation.ROOT)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options) as child:
                child.stdin.write(kwargs['input'])
                child.stdin.close()
                deadline = time.monotonic() + 20
                while not (fenced / 'fence-ready').exists():
                    assert child.poll() is None and time.monotonic() < deadline, 'child did not enter fenced write'
                    time.sleep(.02)
                try:
                    with pytest.raises(PermissionError):
                        source_config.write_bytes(source_bytes + b'\n# unauthorized change\n')
                finally:
                    (fenced / 'fence-continue').write_text('continue', encoding='utf-8')
                output, error = child.stdout.read(), child.stderr.read()
                child.wait(timeout=30)
                return SimpleNamespace(returncode=child.returncode, stdout=output, stderr=error)
        patcher.setattr(subprocess, 'run', fenced_child)
        assert call(monkeypatch, *fenced_args) == 0
        fenced_report = json.loads(capsys.readouterr().out)
    assert fenced_report['status'] == 'complete' and source_config.read_bytes() == source_bytes
    # An already running native host owns the same lock and prevents migration.
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from core.infrastructure.file_lock import locked_sidecar
    held, release = threading.Event(), threading.Event()
    def hold():
        with locked_sidecar(target / 'host-owner'):
            held.set()
            assert release.wait(30)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        try:
            assert held.wait(5)
            assert call(monkeypatch, *args) == 1
            busy_report = json.loads(capsys.readouterr().out)
            assert busy_report['code'] == 'TARGET_PROFILE_BUSY', busy_report
        finally:
            release.set()
            future.result(timeout=30)
    assert call(monkeypatch, *args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'complete' and not report['readyForCutover']
    assert report['knowledge']['importedCount'] == 1
    assert call(monkeypatch, *args) == 0
    assert json.loads(capsys.readouterr().out)['knowledge']['idempotent']
    assert before == {p: p.read_bytes() for p in workspace.rglob('*') if p.is_file()}
    # Native developer policy rejects activation before any knowledge writes;
    # the formal source and its unrelated sentinel remain untouched.
    sandbox_target = tmp_path / 'developer-profile/native'
    sandbox_config = sandbox_target / 'config/config.toml'
    sandbox_config.parent.mkdir(parents=True)
    sandbox_config.write_text(TEST_MODEL_CONFIG + '\n[launcher.developer_mode]\nenabled=true\n', encoding='utf-8')
    formal_sentinel = sandbox_target / 'data/workspace/knowledge/unrelated-sentinel.txt'
    formal_sentinel.parent.mkdir(parents=True)
    formal_sentinel.write_text('DO_NOT_COPY_FORMAL', encoding='utf-8')
    sandbox_args = ('--activate-knowledge', old_id, '--source-config', source_config,
        '--target-profile', sandbox_target, '--target-config', sandbox_config, '--migration-id', 'sandbox-knowledge')
    assert call(monkeypatch, *sandbox_args) == 1
    sandbox_report = json.loads(capsys.readouterr().out)
    assert sandbox_report['reason'] == 'knowledge_native_promotion_blocked'
    assert formal_sentinel.read_text(encoding='utf-8') == 'DO_NOT_COPY_FORMAL'
    assert list(sandbox_target.rglob('unrelated-sentinel.txt')) == [formal_sentinel]
    assert not (sandbox_target / 'knowledge_migrations').exists()
    assert not list((sandbox_target / '.runtime').rglob('knowledge_migrations'))
    _run(new_root, r'''
        import json, os, sys
        from pathlib import Path
        def no_network(event, args):
            if event == 'socket.connect': raise AssertionError('network forbidden')
        sys.addaudithook(no_network)
        from core.assistant_runtime import native
        from core.web.services import team_knowledge_service as knowledge, agent_directory_service as directory
        from tools.team_knowledge_tools import search_agent_private_memory_tool
        knowledge._extended_fs_path = lambda path: Path(path).resolve()
        try:
            detail = native.bootstrap(Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']))['assistant']
            with directory.active_agent_runtime(detail['agentId'], session_id=detail['directSessionId'], turn_id='search'):
                result = json.loads(search_agent_private_memory_tool(query='SYNTHETIC_MIGRATED_KNOWLEDGE', query_mode='exact'))
                assert result['ok'] and result['results']
        finally:
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


def active_personal_case(tmp_path, monkeypatch):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG
    workspace, _ = authorized_fixture(tmp_path, monkeypatch)
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


def test_real_child_uses_explicit_source_data_home_with_competing_canonical_workspace(tmp_path, monkeypatch, capsys):
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    override = tmp_path / 'configured-data'
    shutil.copytree(workspace, override / 'workspace')
    original = workspace / 'agents' / AGENT / 'plugins/personal-affairs/affairs/items.jsonl'
    wrong = json.loads(original.read_text(encoding='utf-8'))
    original.write_text(json.dumps({**wrong, 'title': 'wrong canonical source'}) + '\n', encoding='utf-8')
    registry = workspace / 'agents/agents.json'
    raw = json.loads(registry.read_text(encoding='utf-8'))
    raw['agents'][0]['agentId'] = 'different-pa'
    registry.write_text(json.dumps(raw), encoding='utf-8')
    config = args[3]
    config.write_text('[storage]\ndata_home = ' + json.dumps(str(override).replace('\\', '/'))
                      + '\n[launcher.developer_mode]\nenabled=false\n', encoding='utf-8')
    assert call(monkeypatch, *args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'complete' and not report['sourceQuiesced']
    target_ledger = next(target.glob('agents/*/plugins/personal-affairs/affairs/items.jsonl'))
    assert json.loads(target_ledger.read_text(encoding='utf-8'))['title'] == 'Synthetic task'
    assert 'wrong canonical source' not in target_ledger.read_text(encoding='utf-8')


@pytest.mark.parametrize('authority', ['identity', 'marker'])
def test_child_rejects_project_or_marker_change_before_source_publication(tmp_path, monkeypatch, capsys, authority):
    import subprocess
    from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    project = Path(os.environ['TEST_MIGRATION_PROJECT'])
    path = project / '.vibelution/project.json' if authority == 'identity' else storage_migration_state_path(
        resolve_project_storage_paths(project, projects_home=os.environ['VIBELUTION_PROJECTS_HOME']))
    real_run = subprocess.run
    def change_then_run(*a, **k):
        path.write_bytes(path.read_bytes() + b'\n')
        return real_run(*a, **k)
    monkeypatch.setattr(subprocess, 'run', change_then_run)
    assert call(monkeypatch, *args) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == 'source_authority_changed'
    assert not (target / 'history_sources').exists()


def test_missing_storage_marker_fails_closed_before_child(tmp_path, monkeypatch, capsys):
    from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    project = Path(os.environ['TEST_MIGRATION_PROJECT'])
    marker = storage_migration_state_path(resolve_project_storage_paths(project, projects_home=os.environ['VIBELUTION_PROJECTS_HOME']))
    marker.unlink()
    assert call(monkeypatch, *args) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'SOURCE_MIGRATION_UNAVAILABLE'
    assert not (target / 'history_sources').exists()


@pytest.mark.parametrize('mode', ['environment', 'developer'])
def test_unproven_source_environment_or_developer_route_fails_closed(tmp_path, monkeypatch, capsys, mode):
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    if mode == 'environment':
        monkeypatch.setenv('VIBELUTION_DATA_HOME', str(tmp_path / 'unknown-source'))
        expected = 'source_environment_unverified'
    else:
        args[3].write_text('[launcher.developer_mode]\nenabled=true\n', encoding='utf-8')
        expected = 'source_developer_mode_unverified'
    assert call(monkeypatch, *args) == 1
    assert json.loads(capsys.readouterr().out)['reason'] == expected
    assert not (target / 'history_sources').exists()


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


def test_offline_conflict_preparation_archives_source_and_never_changes_target(tmp_path, monkeypatch, capsys):
    workspace, target, args = active_personal_case(tmp_path, monkeypatch)
    assert call(monkeypatch, *args) == 0
    capsys.readouterr()
    source = workspace / 'agents' / AGENT / 'plugins/personal-affairs/affairs/items.jsonl'
    row = json.loads(source.read_text(encoding='utf-8'))
    source.write_text(json.dumps({**row, 'title': 'source changed'}) + '\n'
                      + json.dumps({**row, 'itemId': 'source-new', 'title': 'new source item'}) + '\n', encoding='utf-8')
    target_ledger = next(target.glob('agents/*/plugins/personal-affairs/affairs/items.jsonl'))
    user_item = {**row, 'title': 'user modified target'}
    target_ledger.write_text(json.dumps(user_item) + '\n', encoding='utf-8')
    before = target_ledger.read_bytes()
    conflict_args = ('--prepare-affairs-conflicts', AGENT, '--source-config', args[3],
        '--target-profile', target, '--target-config', args[7], '--migration-id', 'cli-latest',
        '--baseline-migration-id', 'cli-activation')
    assert call(monkeypatch, *conflict_args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'complete' and not report['sourceQuiesced'] and not report['readyForCutover']
    assert report['conflicts']['conflictCount'] == 2 and not report['conflicts']['reused']
    assert target_ledger.read_bytes() == before
    assert call(monkeypatch, *conflict_args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['conflicts']['reused'] and target_ledger.read_bytes() == before
    records = list((target / 'affairs_conflicts').glob('*.json'))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding='utf-8'))
    changed = next(item for item in record['conflicts'] if item['itemId'] == 'old-todo')
    added = next(item for item in record['conflicts'] if item['itemId'] == 'source-new')
    assert changed['source']['title'] == 'source changed'
    assert changed['target']['title'] == 'user modified target'
    assert added['targetState'] == 'missing' and added['source']['title'] == 'new source item'


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
    lambda: Path('\\\\?\\' + str(source)).write_text('changed'),
    lambda: source.parent.joinpath('unexpected').mkdir(),
    lambda: socket.socket().connect(('127.0.0.1', 9)),
    lambda: subprocess.run([sys.executable, '-c', 'pass']),
):
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('offline isolation escape')
(target / 'allowed.txt').write_text('allowed')
Path('\\\\?\\' + str(target / 'allowed-extended.txt')).write_text('allowed')
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
