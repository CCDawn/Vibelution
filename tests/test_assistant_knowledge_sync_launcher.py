"""Isolated native approval, persistent intent and cold-start Job integration."""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.main_control import initial_migration_id
from scripts import assistant_migration_inventory as cli
from tests.test_assistant_migration_cli import test_initial_offline_real_child_requires_permit_and_never_replays as prepare_baseline
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def _record(target, operation_id, state):
    directory = target.parent / 'initial-migration-results'
    directory.mkdir(exist_ok=True)
    key = hashlib.sha256(operation_id.encode()).hexdigest()
    row = {'schemaVersion': 1, 'request': {'requestId': operation_id, 'projectId': state, 'operation': 'start'},
           'binding': None, 'command': None, 'reservationToken': 'a' * 64}
    (directory / (key + '.json')).write_text(json.dumps(row), encoding='utf-8')


def test_approved_turn_queues_and_cold_start_executes_once(tmp_path, monkeypatch, *, exercise_not_started=True):
    # Existing full initial Job fixture performs a real, drained baseline import.
    prepare_baseline(tmp_path, monkeypatch, 'knowledge', 'canonical', False)
    target = tmp_path / 'native'
    shutil.rmtree(target / 'initial_migration_intents' / ('e' * 64))  # This fixture deliberately inserted corruption.
    initial = initial_migration_id('registered:1', '', 'knowledge')
    _record(target, initial, 'completed')  # Emulates Electron's post-drain durable result.
    baseline = read_initial_intent(target, initial)
    project = Path(os.environ['TEST_MIGRATION_PROJECT'])
    if os.name == 'nt':
        project = Path(project.drive.lower() + str(project)[len(project.drive):])
    source_config = tmp_path / 'source-config.toml'
    from scripts.assistant_migration_activate import storage_authority
    paths, _, _ = storage_authority(project, source_config)
    workspace, _, _, _ = cli._bound_route(paths, source_config)
    legacy = tmp_path / 'legacy'
    (legacy / 'workspace-path.txt').write_text(str(workspace), encoding='utf-8')
    _run(legacy, r'''
        import os, shutil
        from pathlib import Path
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import team_knowledge_service as s
        s._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = Path((root.parent / 'workspace-path.txt').read_text())
        with offline_migration_profile() as lease:
            owner = s._require_owner_context('agent', lease.agent_id)
            base = s._knowledge_bases_for_owner(owner)[0]
            entry = s.collect_source_to_inbox('agent', lease.agent_id, source_type='manual_user_entry',
                original_content='NEW_SYNTHETIC', title='New fixture', actor_agent_id=lease.agent_id)
            s.review_owner_inbox_source('agent', lease.agent_id, entry['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=lease.agent_id, ingest_on_accept=True,
                knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']),
                knowledge_content='NEW_SYNTHETIC')
            output = root.parent / 'copy2'; output.mkdir()
            shutil.copytree(s._knowledge_root_for_owner(owner), output / 'knowledge')
            shutil.copyfile(s._central_source_registry_path(), output / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), output / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    shutil.copytree(legacy / 'copy2/knowledge', workspace / 'agents' / baseline['sourceScope']['agentId'] / 'knowledge', dirs_exist_ok=True)
    for name in ('source_registry.jsonl', 'owner_refs.jsonl'):
        shutil.copyfile(legacy / 'copy2' / name, workspace / 'knowledge/sources/registry' / name)
    (tmp_path / 'launcher-fixture.json').write_text(json.dumps({'project': str(project), 'sourceConfig': str(source_config),
        'projectsHome': os.environ['VIBELUTION_PROJECTS_HOME']}), encoding='utf-8')
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
        dispatch.replace_projects({'schemaVersion': 1, 'revision': 1, 'projects': {'registered:1': fixture['project']}})
        preview = HistoryPreview(dispatch, Path(fixture['sourceConfig']))
        dispatch.history_preview = preview
        owner = HistoryHost(root, 'fixture', dispatch, preview, initial_owner_check=lambda: True)
        with sessions._RUNNING_SESSIONS_LOCK:
            sessions._RUNNING_SESSION_IDS.add(assistant['directSessionId'])
            sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'turn-one'
        async def run():
            broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
            app = create_app(native=object(), token='private-test-token', dispatch=dispatch, history_control=owner, main_control=broker)
            actions.bind_actions(dispatch, asyncio.get_running_loop(), broker)
            p = preview.preview('registered:1', turn_id='turn-one')
            args = {'project_id': 'registered:1', 'preview_id': p['previewId']}
            denied = await asyncio.to_thread(actions.execute_action, 'knowledge_sync_queue', args,
                runtime={'turnId':'turn-one'}, governed=False)
            assert denied['status'] == 'approval_required'
            task = asyncio.create_task(asyncio.to_thread(actions.execute_action, 'knowledge_sync_queue', args,
                runtime={'turnId':'turn-one'}, governed=True))
            wire = (await broker.claim())['request']
            assert wire['category'] == 'knowledge_sync' and wire['operationId'].startswith('ksync-')
            payload = {key: wire[key] for key in ('deliveryId','projectId','previewId','turnId','category','operationId')}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                    headers={'Authorization': 'Bearer private-test-token'}) as client:
                response = await client.post('/api/assistant/initial-migration/prepare', json={**payload, 'revision':1})
                assert response.status_code == 200, response.text
                bound = response.json()
                assert bound['baselineMigrationId'] == ''' + repr(initial) + r'''
            result = {'schemaVersion':1, **{key: wire[key] for key in ('projectId','previewId','category','operationId')},
                      'state':'queued', 'code':'queued', 'readyForCutover':False}
            assert broker.settle(wire['deliveryId'], result)
            assert (await task)['state'] == 'queued'
            receipt = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1','operation_id':wire['operationId']})
            assert receipt['state'] == 'queued'
            (root.parent / 'sync-operation.txt').write_text(wire['operationId'])
            actions.unbind_actions(dispatch)
            broker.close()
        try: asyncio.run(run())
        finally:
            with sessions._RUNNING_SESSIONS_LOCK:
                sessions._RUNNING_SESSION_IDS.discard(assistant['directSessionId'])
                sessions._SESSION_ACTIVE_TURN_IDS.pop(assistant['directSessionId'], None)
            owner.close()
            assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
    sync_id = (tmp_path / 'sync-operation.txt').read_text()
    intent = read_initial_intent(target, sync_id)
    assert intent['baselineMigrationId'] == initial and intent['sourceScope'] == baseline['sourceScope']
    token = 'a' * 64
    binding = {'schemaVersion':1, 'registeredProjectId':'registered:1', 'revision':1, 'projectRoot':str(project),
        'sourceConfig':str(source_config), 'targetProfile':str(target),
        'targetConfig':str(target / ('.initial-migration-models-v1-' + sync_id + '-' + intent['registryDigest'] + '.toml')),
        'operationId':sync_id}
    calls = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            assert self.headers.get('Authorization') == 'Bearer ' + token
            raw = json.dumps(binding).encode(); self.send_response(200); self.end_headers(); self.wfile.write(raw)
        def do_POST(self):
            assert self.headers.get('Authorization') == 'Bearer ' + token
            assert self.rfile.read(int(self.headers['Content-Length'])) == b'{}'
            calls.append('permit')
            raw = b'{"schemaVersion":1,"granted":true}'; self.send_response(200); self.end_headers(); self.wfile.write(raw)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    env = {k:v for k,v in os.environ.items() if not k.upper().startswith('VIBELUTION_')}
    env.update({'VIBELUTION_PROJECTS_HOME':os.environ['VIBELUTION_PROJECTS_HOME'],
        'VIBELUTION_INITIAL_MIGRATION_URL':'http://127.0.0.1:' + str(server.server_port),
        'VIBELUTION_INITIAL_MIGRATION_TOKEN':token, 'PYTHONIOENCODING':'utf-8',
        'USERPROFILE':str(tmp_path / 'user'), 'HOME':str(tmp_path / 'user'),
        'LOCALAPPDATA':str(tmp_path / 'user/AppData/Local'), 'APPDATA':str(tmp_path / 'user/AppData/Roaming'),
        'TEMP':str(tmp_path / 'tmp'), 'TMP':str(tmp_path / 'tmp')})
    try:
        _record(target, sync_id + '.attempt', 'unknown')
        command = [sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'), '--initial-offline']
        result = subprocess.run(command, env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)['state'] == 'completed' and calls == ['permit']
        verify = subprocess.run([sys.executable, str(cli.ROOT / 'scripts/assistant_migration_inventory.py'),
            '--initial-verify', '--target-profile', str(target), '--operation-id', sync_id],
            env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert verify.returncode == 0, (verify.stdout, verify.stderr)
        _record(target, sync_id, 'completed')  # Only after owned Job and verification drained.
        again = subprocess.run(command, env=env, cwd=cli.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
        assert again.returncode != 0 and json.loads(again.stdout)['state'] == 'unknown' and calls == ['permit']
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    _run(tmp_path, r'''
        import hashlib, os
        from pathlib import Path
        from types import SimpleNamespace
        from core.assistant_runtime import actions, native
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        operation = (root.parent / 'sync-operation.txt').read_text()
        before = {p.relative_to(root).as_posix():p.read_bytes() for p in (root / 'knowledge_migrations').rglob('*') if p.is_file()}
        native.bootstrap(root)
        import json
        project = Path(json.loads((root.parent / 'launcher-fixture.json').read_text())['project'])
        service = SimpleNamespace(project_ids=lambda: ['registered:1', 'other:1'], _registry_revision=1,
                                  _admitted_projects=lambda: {'registered:1':project, 'other:1':project})
        actions.bind_actions(service, None, SimpleNamespace(initial_migration_enabled=True, appearance_enabled=False))
        try:
            result = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':operation})
            assert result['state'] == 'completed' and result['plannedAppliedCount'] == 1
            assert result['pendingCount'] == result['skippedCount'] == 0
            assert actions.execute_action('knowledge_sync_receipt', {'project_id':'other:1', 'operation_id':operation})['state'] == 'unknown'
            projects = service._admitted_projects
            def suspended(): raise ValueError('registry suspended')
            service._admitted_projects = suspended
            assert actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':operation})['state'] == 'unknown'
            service._admitted_projects = projects
            result_path = root.parent / 'initial-migration-results' / (hashlib.sha256(operation.encode()).hexdigest() + '.json')
            saved = result_path.read_bytes(); result_path.unlink()
            try:
                assert actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':operation})['state'] == 'unknown'
            finally: result_path.write_bytes(saved)
            from core.assistant_runtime.migration_knowledge import _digest
            folder = root / 'knowledge_migrations/sync_operations'
            plan_path, receipt_path = [folder / (_digest(operation) + suffix) for suffix in ('.plan.json', '.complete.json')]
            original_plan, original_receipt = plan_path.read_bytes(), receipt_path.read_bytes()
            plan, receipt = json.loads(original_plan), json.loads(original_receipt)
            plan['excludedCount'] = 1; receipt['planSha256'] = _digest(plan)
            plan_path.write_text(json.dumps(plan)); receipt_path.write_text(json.dumps(receipt))
            try:
                partial = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1', 'operation_id':operation})
                assert partial['state'] == 'partial' and partial['excludedCount'] == 1
            finally:
                plan_path.write_bytes(original_plan); receipt_path.write_bytes(original_receipt)
            after = {p.relative_to(root).as_posix():p.read_bytes() for p in (root / 'knowledge_migrations').rglob('*') if p.is_file()}
            assert before == after
        finally:
            actions.unbind_actions(service)
            assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
    from core.assistant_runtime.initial_migration_binding import publish_initial_intent
    from core.assistant_runtime.main_control import knowledge_sync_id
    from core.assistant_runtime.migration_io import MigrationIOError
    import pytest
    class Token:
        def publish(self, write): write()
        def check(self): pass
    preview = 'd' * 64
    second = {**intent, 'previewId':preview, 'operationId':knowledge_sync_id('registered:1', preview), 'turnId':'turn-two'}
    publish_initial_intent(target, second, Token(), lambda: None, owner_check=lambda: True)
    assert read_initial_intent(target, second['operationId']) == second
    preview = 'e' * 64
    third = {**second, 'previewId':preview, 'operationId':knowledge_sync_id('registered:1', preview), 'turnId':'turn-three'}
    with pytest.raises(MigrationIOError, match='knowledge_sync_prior_unknown'):
        publish_initial_intent(target, third, Token(), lambda: None, owner_check=lambda: True)
    assert read_initial_intent(target, third['operationId']) is None
    if exercise_not_started:
        _record(target, second['operationId'] + '.attempt', 'unknown')
        _record(target, second['operationId'], 'not_started')
        from core.assistant_runtime.knowledge_not_started import read_verified_not_started
        assert read_verified_not_started(target, second['operationId'])
        publish_initial_intent(target, third, Token(), lambda: None, owner_check=lambda: True)
        assert read_initial_intent(target, third['operationId']) == third
        (tmp_path / 'not-started-operation.txt').write_text(second['operationId'])
        _run(tmp_path, r'''
        import json, os
        from pathlib import Path
        from types import SimpleNamespace
        from core.assistant_runtime import actions, native
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        fixture = json.loads((root.parent / 'launcher-fixture.json').read_text())
        project = Path(fixture['project']); operation = (root.parent / 'not-started-operation.txt').read_text()
        native.bootstrap(root)
        service = SimpleNamespace(project_ids=lambda:['registered:1'], _registry_revision=1,
                                  _admitted_projects=lambda:{'registered:1':project})
        actions.bind_actions(service, None, SimpleNamespace(initial_migration_enabled=True, appearance_enabled=False))
        try:
            result = actions.execute_action('knowledge_sync_receipt', {'project_id':'registered:1','operation_id':operation})
            assert result['state'] == 'not_started' and result['operationId'] == operation
        finally:
            actions.unbind_actions(service); assert native.shutdown()['closed']
        ''', config_text=TEST_MODEL_CONFIG)
