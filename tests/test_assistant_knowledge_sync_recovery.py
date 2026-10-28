"""Recover an original sync ID through the approved, isolated cold-start path."""
import json
import os
import shutil
import subprocess
import sys
import threading
import http.server
from pathlib import Path

import pytest

from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.main_control import knowledge_sync_id
from scripts import assistant_migration_inventory as cli
from tests.test_assistant_knowledge_sync_launcher import _record, test_approved_turn_queues_and_cold_start_executes_once as prepare_case
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


@pytest.mark.parametrize('interruption', ['published', 'started_unknown', 'finished', 'source_changed'])
def test_recovery_uses_original_id_and_never_replays_unknown_write(tmp_path, monkeypatch, interruption):
    prepare_case(tmp_path, monkeypatch, exercise_not_started=False)
    root = tmp_path / 'native'
    original = knowledge_sync_id('registered:1', 'd' * 64)
    intent = read_initial_intent(root, original)
    fixture = json.loads((tmp_path / 'launcher-fixture.json').read_text())
    project, source_config = Path(fixture['project']), Path(fixture['sourceConfig'])
    from scripts.assistant_migration_activate import storage_authority
    paths, _, _ = storage_authority(project, source_config)
    workspace, _, _, _ = cli._bound_route(paths, source_config)
    legacy = tmp_path / 'legacy'
    _run(legacy, r'''
        import os, shutil
        from pathlib import Path
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import team_knowledge_service as s
        s._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        with offline_migration_profile() as lease:
            owner = s._require_owner_context('agent', lease.agent_id)
            base = s._knowledge_bases_for_owner(owner)[0]
            for text in ('RECOVERY_FIXTURE_ONE', 'RECOVERY_FIXTURE_TWO'):
                entry = s.collect_source_to_inbox('agent', lease.agent_id, source_type='manual_user_entry',
                    original_content=text, title=text, actor_agent_id=lease.agent_id)
                s.review_owner_inbox_source('agent', lease.agent_id, entry['inboxSourceId'], decision='accepted',
                    reviewed_by_agent_id=lease.agent_id, ingest_on_accept=True,
                    knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']), knowledge_content=text)
            out = root.parent / 'copy3'; out.mkdir()
            shutil.copytree(s._knowledge_root_for_owner(owner), out / 'knowledge')
            shutil.copyfile(s._central_source_registry_path(), out / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), out / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    shutil.copytree(legacy / 'copy3/knowledge', workspace / 'agents' / intent['sourceScope']['agentId'] / 'knowledge', dirs_exist_ok=True)
    for name in ('source_registry.jsonl', 'owner_refs.jsonl'):
        shutil.copyfile(legacy / 'copy3' / name, workspace / 'knowledge/sources/registry' / name)

    def run_job(operation_id, *, inject=None):
        current = read_initial_intent(root, operation_id)
        binding = {'schemaVersion':1, 'registeredProjectId':'registered:1', 'revision':1, 'projectRoot':str(project),
            'sourceConfig':str(source_config), 'targetProfile':str(root),
            'targetConfig':str(root / ('.initial-migration-models-v1-' + operation_id + '-' + current['registryDigest'] + '.toml')),
            'operationId':operation_id}
        calls = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_GET(self):
                raw = json.dumps(binding).encode(); self.send_response(200); self.end_headers(); self.wfile.write(raw)
            def do_POST(self):
                assert self.rfile.read(int(self.headers['Content-Length'])) == b'{}'
                calls.append('permit'); raw = b'{"schemaVersion":1,"granted":true}'
                self.send_response(200); self.end_headers(); self.wfile.write(raw)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        env = {k:v for k,v in os.environ.items() if not k.upper().startswith('VIBELUTION_')}
        env.update({'VIBELUTION_PROJECTS_HOME':fixture['projectsHome'],
            'VIBELUTION_INITIAL_MIGRATION_URL':'http://127.0.0.1:' + str(server.server_port),
            'VIBELUTION_INITIAL_MIGRATION_TOKEN':'a' * 64, 'PYTHONIOENCODING':'utf-8',
            'USERPROFILE':str(tmp_path / 'user'), 'HOME':str(tmp_path / 'user'),
            'LOCALAPPDATA':str(tmp_path / 'user/AppData/Local'), 'APPDATA':str(tmp_path / 'user/AppData/Roaming'),
            'TEMP':str(tmp_path / 'tmp'), 'TMP':str(tmp_path / 'tmp')})
        try:
            preflight = subprocess.run([sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'),
                '--knowledge-preflight', '--source-config', str(source_config), '--target-profile', str(root),
                '--target-config', binding['targetConfig'], '--operation-id', operation_id,
                '--registry-digest', current['registryDigest']], env=env, cwd=cli.ROOT,
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            assert preflight.returncode == 0 and json.loads(preflight.stdout)['state'] == 'ready', (preflight.stdout, preflight.stderr)
            _record(root, operation_id + '.attempt', 'unknown')
            if inject:
                child = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from scripts import assistant_migration_activate as entry
from core.assistant_runtime import migration_knowledge as knowledge
mode = sys.argv[2]
if mode == 'published':
    original = knowledge._import_one
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(97)
    knowledge._import_one = interrupted
elif mode == 'started_unknown':
    original = knowledge._immutable
    def interrupted(path, value):
        original(path, value)
        if path.name.endswith('.intent.json'): os._exit(97)
    knowledge._immutable = interrupted
else:
    original = knowledge._immutable
    def interrupted(path, value):
        if path.parent.name == 'sync_operations' and path.name.endswith('.complete.json'): os._exit(97)
        original(path, value)
    knowledge._immutable = interrupted
raise SystemExit(entry._child())
'''
                wrapper = r'''
import subprocess, sys
sys.path.insert(0, sys.argv[1])
from scripts import assistant_migration_inventory as entry
real_run = subprocess.run
child, root, mode = sys.argv[2], sys.argv[1], sys.argv[3]
def intercept(command, **kwargs):
    return real_run([sys.executable, '-I', '-B', '-c', child, root, mode], **kwargs)
subprocess.run = intercept
raise SystemExit(entry._initial_offline())
'''
                command = [sys.executable, '-c', wrapper, str(cli.ROOT), child, inject]
            else:
                command = [sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'), '--initial-offline']
            result = subprocess.run(command, env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
            return result, json.loads(result.stdout), calls, env
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    result, original_outcome, calls, env = run_job(original, inject='published' if interruption == 'source_changed' else interruption)
    assert result.returncode != 0 and original_outcome['state'] == 'unknown' and calls == ['permit']
    if interruption == 'source_changed':
        _run(legacy, r'''
            import os, shutil
            from pathlib import Path
            from core.assistant_runtime.migration_profile import offline_migration_profile
            from core.web.services import team_knowledge_service as s
            s._extended_fs_path = lambda path: Path(path).resolve()
            root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
            with offline_migration_profile() as lease:
                owner = s._require_owner_context('agent', lease.agent_id)
                base = s._knowledge_bases_for_owner(owner)[0]
                entry = s.collect_source_to_inbox('agent', lease.agent_id, source_type='manual_user_entry',
                    original_content='AFTER_INTERRUPTION', title='Later fixture', actor_agent_id=lease.agent_id)
                s.review_owner_inbox_source('agent', lease.agent_id, entry['inboxSourceId'], decision='accepted',
                    reviewed_by_agent_id=lease.agent_id, ingest_on_accept=True,
                    knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']), knowledge_content='AFTER_INTERRUPTION')
                out = root.parent / 'copy4'; out.mkdir()
                shutil.copytree(s._knowledge_root_for_owner(owner), out / 'knowledge')
                shutil.copyfile(s._central_source_registry_path(), out / 'source_registry.jsonl')
                shutil.copyfile(s._central_owner_refs_path(), out / 'owner_refs.jsonl')
        ''', config_text=TEST_MODEL_CONFIG)
        shutil.copytree(legacy / 'copy4/knowledge', workspace / 'agents' / intent['sourceScope']['agentId'] / 'knowledge', dirs_exist_ok=True)
        for name in ('source_registry.jsonl', 'owner_refs.jsonl'):
            shutil.copyfile(legacy / 'copy4' / name, workspace / 'knowledge/sources/registry' / name)
    (tmp_path / 'original-sync.txt').write_text(original, encoding='utf-8')
    _run(tmp_path, r'''
        import asyncio, json, os
        from pathlib import Path
        import httpx
        from core.assistant_runtime import actions, native
        from core.assistant_runtime.dispatch import DispatchService
        from core.assistant_runtime.history_preview import HistoryPreview
        from core.assistant_runtime.history_host import HistoryHost
        from core.assistant_runtime.host import create_app
        from core.assistant_runtime.main_control import MainControlBroker
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        fixture = json.loads((root.parent / 'launcher-fixture.json').read_text())
        os.environ['VIBELUTION_PROJECTS_HOME'] = fixture['projectsHome']
        assistant = native.bootstrap(root)['assistant']
        dispatch = DispatchService(root, {})
        dispatch.replace_projects({'schemaVersion':1,'revision':1,'projects':{'registered:1':fixture['project']}})
        preview = HistoryPreview(dispatch, Path(fixture['sourceConfig'])); dispatch.history_preview = preview
        owner = HistoryHost(root, 'fixture', dispatch, preview, initial_owner_check=lambda: True)
        with sessions._RUNNING_SESSIONS_LOCK:
            sessions._RUNNING_SESSION_IDS.add(assistant['directSessionId'])
            sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'turn-recover'
        async def run():
            broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
            app = create_app(native=object(), token='private-test-token', dispatch=dispatch, history_control=owner, main_control=broker)
            actions.bind_actions(dispatch, asyncio.get_running_loop(), broker)
            original = (root.parent / 'original-sync.txt').read_text()
            before = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':original})
            assert before['state'] == 'unknown'
            p = preview.preview('registered:1', turn_id='turn-recover')
            args = {'project_id':'registered:1', 'preview_id':p['previewId'], 'operation_id':original}
            denied = await asyncio.to_thread(actions.execute_action, 'knowledge_sync_recover', args,
                runtime={'turnId':'turn-recover'}, governed=False)
            assert denied['status'] == 'approval_required'
            task = asyncio.create_task(asyncio.to_thread(actions.execute_action, 'knowledge_sync_recover', args,
                runtime={'turnId':'turn-recover'}, governed=True))
            wire = (await broker.claim())['request']
            assert wire['category'] == 'knowledge_recovery' and wire['originalSyncId'] == original
            payload = {key:wire[key] for key in ('deliveryId','projectId','previewId','turnId','category','operationId','originalSyncId')}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                    headers={'Authorization':'Bearer private-test-token'}) as client:
                response = await client.post('/api/assistant/initial-migration/prepare', json={**payload,'revision':1})
                assert response.status_code == 200, response.text
            result = {'schemaVersion':1, **{key:wire[key] for key in ('projectId','previewId','category','operationId','originalSyncId')},
                      'state':'queued','code':'queued','readyForCutover':False}
            assert broker.settle(wire['deliveryId'], result)
            ack = await task
            assert ack['operationId'] == original and ack['recoveryId'] == wire['operationId'] and ack['state'] == 'queued'
            (root.parent / 'recovery-job.txt').write_text(wire['operationId'])
            actions.unbind_actions(dispatch); broker.close()
        try: asyncio.run(run())
        finally:
            with sessions._RUNNING_SESSIONS_LOCK:
                sessions._RUNNING_SESSION_IDS.discard(assistant['directSessionId'])
                sessions._SESSION_ACTIVE_TURN_IDS.pop(assistant['directSessionId'], None)
            owner.close(); assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
    recovery = (tmp_path / 'recovery-job.txt').read_text()
    before = {p.relative_to(root).as_posix():p.read_bytes() for p in (root / 'knowledge_migrations').rglob('*') if p.is_file()}
    result, outcome, calls, env = run_job(recovery)
    assert calls == ['permit']
    if interruption == 'started_unknown':
        assert result.returncode != 0 and outcome['state'] == 'unknown'
        after = {p.relative_to(root).as_posix():p.read_bytes() for p in (root / 'knowledge_migrations').rglob('*') if p.is_file()}
        assert before == after
    else:
        expected = 'partial' if interruption == 'source_changed' else 'completed'
        assert result.returncode == 0 and outcome['state'] == expected, (result.stdout, result.stderr)
        if interruption == 'finished':
            item_prefix = 'knowledge_migrations/sync_items/'
            after = {p.relative_to(root).as_posix():p.read_bytes() for p in (root / 'knowledge_migrations/sync_items').rglob('*') if p.is_file()}
            assert {k:v for k,v in before.items() if k.startswith(item_prefix)} == after
        verification = subprocess.run([sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'),
            '--initial-verify', '--target-profile', str(root), '--operation-id', recovery,
            *(['--allow-partial'] if expected == 'partial' else [])],
            env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert verification.returncode == 0, (verification.stdout, verification.stderr)
        _record(root, recovery, expected)
        from core.assistant_runtime.knowledge_sync_receipt import read_knowledge_sync_receipt
        proof = read_knowledge_sync_receipt(root, sync_id=original, baseline_id=intent['baselineMigrationId'],
            source_scope=intent['sourceScope'], target_agent_id=intent['targetAgentId'])
        assert proof['state'] == expected and proof['plannedAppliedCount'] == (1 if expected == 'partial' else 2)
        if expected == 'partial':
            assert proof['pendingCount'] == proof['skippedCount'] == 1
    expected_state = 'unknown' if interruption == 'started_unknown' else 'partial' if interruption == 'source_changed' else 'completed'
    _run(tmp_path, '        expected_state = ' + repr(expected_state) + '\n' + r'''
        import json, os
        from pathlib import Path
        from types import SimpleNamespace
        from core.assistant_runtime import actions, native
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        fixture = json.loads((root.parent / 'launcher-fixture.json').read_text())
        project = Path(fixture['project'])
        original = (root.parent / 'original-sync.txt').read_text()
        native.bootstrap(root)
        service = SimpleNamespace(project_ids=lambda: ['registered:1', 'other:1'], _registry_revision=1,
            _admitted_projects=lambda: {'registered:1':project, 'other:1':project})
        actions.bind_actions(service, None, SimpleNamespace(initial_migration_enabled=True, appearance_enabled=False))
        try:
            result = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':original})
            assert result['state'] == expected_state and result['operationId'] == original
            assert actions.execute_action('knowledge_sync_receipt', {'project_id':'other:1', 'operation_id':original})['state'] == 'unknown'
            if expected_state in ('completed', 'partial'):
                import hashlib
                recovery = (root.parent / 'recovery-job.txt').read_text()
                claim = root / 'initial_migration_claims' / recovery / 'claim.json'
                attempt = root.parent / 'initial-migration-results' / (hashlib.sha256((recovery + '.attempt').encode()).hexdigest() + '.json')
                for path in (claim, attempt):
                    saved = path.read_bytes(); path.write_bytes(b'{}')
                    try:
                        assert actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':original})['state'] == 'unknown'
                    finally: path.write_bytes(saved)
        finally:
            actions.unbind_actions(service); assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
    from core.assistant_runtime.initial_migration_binding import publish_initial_intent
    from core.assistant_runtime.migration_io import MigrationIOError
    class Token:
        def publish(self, write): write()
        def check(self): pass
    preview = 'e' * 64
    following = {**intent, 'previewId':preview, 'operationId':knowledge_sync_id('registered:1', preview), 'turnId':'turn-next'}
    if interruption == 'started_unknown':
        with pytest.raises(MigrationIOError, match='knowledge_sync_prior_unknown'):
            publish_initial_intent(root, following, Token(), lambda: None, owner_check=lambda: True)
        assert read_initial_intent(root, following['operationId']) is None
    else:
        publish_initial_intent(root, following, Token(), lambda: None, owner_check=lambda: True)
        assert read_initial_intent(root, following['operationId']) == following
