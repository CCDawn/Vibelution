"""Exercise the offline worker with real source and target processes."""
import textwrap
import subprocess
import pytest

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


@pytest.mark.parametrize('configured', [True, False], ids=['configured-home', 'default-home'])
def test_offline_worker_snapshot_sync_and_original_recovery(tmp_path, configured, monkeypatch):
    # This fixture includes several real owned processes and can take longer
    # than the native helper's single-operation timeout on a busy host.
    run = subprocess.run
    def longer_fixture(*args, **kwargs):
        if kwargs.get('timeout') == 90:
            kwargs['timeout'] = 180
            command = args[0]
            if len(command) == 3 and command[1] == '-c' and len(command[2]) > 20000:
                script = tmp_path / 'fixture-main.py'
                script.write_text('import os, sys; sys.path.insert(0, os.getcwd())\n' + command[2], encoding='utf-8')
                args = ([command[0], '-B', str(script)], *args[1:])
        return run(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', longer_fixture)
    _run(tmp_path, textwrap.dedent(r'''
        import hashlib, json, os, shutil, subprocess, sys, textwrap
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.dispatch import DispatchService
        from core.assistant_runtime.history_preview import HistoryPreview
        from core.assistant_runtime.initial_migration_binding import (_intent_anchor, authority_identity, source_identity, target_identity)
        from core.assistant_runtime.main_control import initial_migration_id
        from core.assistant_runtime.reminder_handoff_intent import handoff_id, sync_id
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.reminder_receipts import ReminderReceiptStore
        from core.assistant_runtime.reminder_source_identity import observe_reminder_source
        from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
        from core.web.services import personal_affairs_service
        from tests.test_assistant_migration_history import source, write_json
        from vibelution_storage import resolve_active_project_storage_paths

        work = Path(os.environ['ASSISTANT_TEST_WRITE_ROOT'])
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = source(work / 'source')
        project = workspace.parent.resolve()
        write_json(project / '.vibelution/project.json', {'schemaVersion': 1, 'projectId': 'source-project'})
        data = json.loads((workspace / 'agents/agents.json').read_text(encoding='utf-8'))
        data['agents'][0]['primaryMode'] = 'general'
        (workspace / 'agents/agents.json').write_text(json.dumps(data), encoding='utf-8')
        config = Path(os.environ['VIBELUTION_CONFIG_PATH'])
        Path(os.environ['VIBELUTION_PROJECTS_HOME']).mkdir(parents=True, exist_ok=True)
        if __CONFIGURED__:
            source_home = work / 'formal-source'
            config.write_text(config.read_text(encoding='utf-8') + '\n[storage]\ndata_home = ' + json.dumps(str(source_home)) + '\n', encoding='utf-8')
        else:
            source_home = Path(os.environ['USERPROFILE']) / 'Documents/Vibelution/data'
            (project / '.git').mkdir()
        shutil.copytree(workspace, source_home / 'workspace')
        active = resolve_active_project_storage_paths(project, config_path=config).data / 'workspace'
        if __CONFIGURED__:
            shutil.copytree(workspace, active)
        dispatch = DispatchService(root, {})
        dispatch.replace_projects({'schemaVersion': 1, 'revision': 1, 'projects': {'registered:1': str(project)}})
        preview = HistoryPreview(dispatch, config)
        def row(item_id, title):
            return {'schemaVersion': 1, 'itemId': item_id, 'kind': 'todo', 'title': title,
                    'status': 'open', 'dueAt': '2020-01-01T00:00:00Z', 'createdAt': '2025-02-01T00:00:00Z'}
        old, new = [row('old', 'before')], [row('old', 'after'), row('new', 'source')]
        raw = lambda rows: b''.join(json.dumps(r).encode() + b'\n' for r in rows)
        ledger = project / 'agents/agent-pa/plugins/personal-affairs/affairs/items.jsonl'
        ledger.parent.mkdir(parents=True)
        ledger.write_bytes(raw(new))
        initial = native.bootstrap(root)['assistant']
        assert native.shutdown()['closed']
        with observe_reminder_source(dispatch, preview, 'registered:1', 1) as observed:
            paths = preview._previews[observed._token][5]
            source_workspace = preview._previews[observed._token][4]
            scope = {'projectId': paths.project_id, 'instanceId': paths.instance_id, 'agentId': observed.agent_id}
            initial_id = initial_migration_id('registered:1', '', 'personal')
            old_hash = hashlib.sha256(raw(old)).hexdigest()
            base = root / 'history_sources/migrations' / initial_id
            item = base / 'sources/mps-ref/affairs/items.jsonl'
            item.parent.mkdir(parents=True)
            item.write_bytes(raw(old))
            (base / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'migrationId': initial_id,
                'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
                'sourceRef': 'mps-ref', 'category': 'personal_affairs', 'path': 'sources/mps-ref/affairs/items.jsonl',
                'sha256': old_hash, 'size': len(raw(old))}]}))
            (base / '.confirmed').mkdir()
            receipts = root / 'affairs_migrations'
            receipts.mkdir()
            (receipts / (hashlib.sha256(initial_id.encode()).hexdigest() + '.json')).write_text(json.dumps({
                'schemaVersion': 1, 'migrationId': initial_id, 'sourceScope': scope, 'sourceSha256': old_hash,
                'targetAgentId': initial['agentId'], 'itemCount': 1, 'published': True}))
            source_digest, project_id, workspace_id = source_identity(scope, project, source_workspace)
            target_digest, target_id = target_identity(root, initial['agentId'], initial['directSessionId'])
            intent = {'schemaVersion': 1, 'registeredProjectId': 'registered:1', 'sourceScope': scope,
                'category': 'personal', 'turnId': 'approved-turn', 'operationId': initial_id, 'revision': 1,
                'sourceIdentityDigest': source_digest, 'registryDigest': '0' * 64, 'targetIdentityDigest': target_digest,
                'projectDirectory': project_id, 'workspaceDirectory': workspace_id, 'targetDirectory': target_id,
                'targetAgentId': initial['agentId'], 'targetSessionId': initial['directSessionId'],
                'authority': 'native_policy_admitted', 'readyForCutover': False}
            template = {**intent, 'category': 'reminder_handoff',
                        'registryDigest': authority_identity(preview._previews[observed._token][7]),
                        'baselineId': None, 'baselineState': 'unknown'}
            def write_handoff(registration):
                handoff = {**template, 'registeredProjectId': registration, 'operationId': handoff_id(registration),
                           'syncId': sync_id(registration)}
                folder = root / 'reminder_handoff_intents' / hashlib.sha256(handoff['operationId'].encode()).hexdigest()
                folder.mkdir(parents=True)
                (folder / 'intent.json').write_text(json.dumps(handoff), encoding='utf-8')
            primary_sync = sync_id('registered:1')
            with offline_migration_profile() as target:
                personal_affairs_service.get_personal_affairs_service().store.write_jsonl(
                    target.agent_id, 'affairs/items.jsonl', old + [row('target-only', 'target')])

            code = textwrap.dedent(r"""
                import json, os, sys
                from pathlib import Path
                from core.assistant_runtime.dispatch import DispatchService
                from core.assistant_runtime.history_preview import HistoryPreview
                from core.assistant_runtime.reminder_source_identity import observe_reminder_source
                from core.assistant_runtime.reminder_offline_worker import run_reminder_offline_worker
                from core.assistant_runtime import reminder_offline_worker as worker
                from core.assistant_runtime import reminder_uncertain_preparation as preparation
                from core.assistant_runtime import reminder_receipts
                root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
                dispatch = DispatchService(root, {})
                dispatch.replace_projects({'schemaVersion':1,'revision':1,'projects':{sys.argv[5]:sys.argv[1]}})
                preview = HistoryPreview(dispatch, Path(os.environ['VIBELUTION_CONFIG_PATH']))
                with observe_reminder_source(dispatch, preview, sys.argv[5], 1) as observed:
                    if sys.argv[2] == 'after-archive':
                        def interrupted_conflicts(*args, **kwargs): os._exit(76)
                        worker.prepare_affairs_conflicts = interrupted_conflicts
                    if sys.argv[2] == 'sync-intent':
                        def interrupted_sync(*args, **kwargs): os._exit(77)
                        worker.reconcile_affairs = interrupted_sync
                    if sys.argv[2] == 'crash':
                        original = preparation.atomic_write_json
                        def interrupt(path, payload, **kwargs):
                            if str(path).endswith('.done.json'): os._exit(73)
                            return original(path, payload, **kwargs)
                        preparation.atomic_write_json = interrupt
                    if sys.argv[2] == 'before-intent':
                        original = preparation.atomic_write_json
                        def interrupt_intent(path, payload, **kwargs):
                            if str(path).endswith('.intent.json'): os._exit(75)
                            return original(path, payload, **kwargs)
                        preparation.atomic_write_json = interrupt_intent
                    if sys.argv[2] == 'provision-crash':
                        from contextlib import contextmanager
                        original_pin = reminder_receipts._pin_leaf
                        @contextmanager
                        def interrupted_pin(path, *, create):
                            with original_pin(path, create=create):
                                os._exit(74)
                                yield
                        reminder_receipts._pin_leaf = interrupted_pin
                    try:
                        result = run_reminder_offline_worker(source=observed, sync_id=sys.argv[4], check_admission=lambda: None,
                            mode='start' if sys.argv[2] in ('after-archive', 'sync-intent', 'fresh') else 'resume',
                            recovery_id=None if sys.argv[2] in ('crash', 'before-intent', 'provision-crash', 'fresh', 'after-archive', 'sync-intent', 'resume') else sys.argv[2])
                        print(json.dumps(result))
                    except Exception as error:
                        print(json.dumps({'error': str(error)}))
            """)
            def launch(mode, baseline='initial', sync=None, registration='registered:1'):
                return subprocess.run([sys.executable, '-B', '-c', code, str(project), mode, baseline,
                                       sync or primary_sync, registration], cwd=Path.cwd(),
                    env=os.environ.copy(), capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            mutex = try_acquire_reminder_source_mutex(observed)
            try:
                busy = launch('fresh')
                assert json.loads(busy.stdout)['error'] == 'reminder_worker_source_busy', busy.stderr
            finally:
                mutex.release()
            missing = launch('fresh')
            assert json.loads(missing.stdout)['error'] == 'reminder_worker_handoff_authority_unavailable', missing.stderr
            write_handoff('registered:1')
            handoff_file = root / 'reminder_handoff_intents' / hashlib.sha256(handoff_id('registered:1').encode()).hexdigest() / 'intent.json'
            original_handoff = handoff_file.read_bytes()
            tampered_handoff = json.loads(original_handoff); tampered_handoff['sourceIdentityDigest'] = '0' * 64
            handoff_file.write_text(json.dumps(tampered_handoff), encoding='utf-8')
            mismatch_handoff = launch('fresh')
            assert json.loads(mismatch_handoff.stdout)['error'] == 'reminder_worker_handoff_authority_unavailable', mismatch_handoff.stderr
            assert not (root / 'reminder_offline_operations').exists()
            handoff_file.write_bytes(original_handoff)
            # Legacy receipts without the original physical authority cannot
            # become an automatically selected baseline.
            no_authority = launch('fresh')
            assert json.loads(no_authority.stdout)['error'] == 'reminder_worker_baseline_authority_unavailable', no_authority.stderr
            assert not (root / 'reminder_offline_operations').exists()
            intent_dir = root / 'initial_migration_intents' / _intent_anchor(intent)
            intent_dir.parent.mkdir(parents=True)
            other_workspace = work / 'different-source-workspace'
            other_workspace.mkdir()
            other_digest, _, other_identity = source_identity(scope, project, other_workspace)
            other_intent = {**intent, 'sourceIdentityDigest': other_digest, 'workspaceDirectory': other_identity}
            # A valid old intent for a different physical workspace cannot
            # authorize this source even when project and Agent IDs match.
            other_dir = root / 'initial_migration_intents' / _intent_anchor(other_intent)
            other_dir.mkdir()
            (other_dir / 'intent.json').write_text(json.dumps(other_intent), encoding='utf-8')
            mismatch = launch('fresh')
            assert json.loads(mismatch.stdout)['error'] == 'reminder_worker_baseline_authority_unavailable', mismatch.stderr
            assert not (root / 'reminder_offline_operations').exists()
            (other_dir / 'intent.json').unlink()
            other_dir.rmdir()
            intent_dir.mkdir()
            (intent_dir / 'intent.json').write_text(json.dumps(intent), encoding='utf-8')
            first = launch('after-archive')
            assert first.returncode == 76, first.stderr + first.stdout
            claim_path = root / 'reminder_offline_operations' / (hashlib.sha256(primary_sync.encode()).hexdigest() + '.intent.json')
            assert json.loads(claim_path.read_text())['baselineId'] == initial_id
            if __CONFIGURED__:
                claim = root / 'reminder_offline_operations' / (hashlib.sha256(primary_sync.encode()).hexdigest() + '.intent.json')
                original_claim = claim.read_bytes()
                tampered = json.loads(original_claim); tampered['schemaVersion'] = True
                claim.write_text(json.dumps(tampered), encoding='utf-8')
                invalid = launch('resume')
                assert json.loads(invalid.stdout)['error'] == 'reminder_worker_binding_changed', invalid.stderr
                claim.write_bytes(original_claim)
            before_intent = launch('before-intent')
            assert before_intent.returncode == 75, before_intent.stderr + before_intent.stdout
            if __CONFIGURED__:
                sync_intent = root / 'reminder_offline_operations' / (hashlib.sha256(primary_sync.encode()).hexdigest() + '.sync-intent.json')
                original_sync = sync_intent.read_bytes()
                tampered = json.loads(original_sync); tampered['schemaVersion'] = True
                sync_intent.write_text(json.dumps(tampered), encoding='utf-8')
                invalid = launch('resume')
                assert json.loads(invalid.stdout)['error'] == 'reminder_worker_binding_changed', invalid.stderr
                sync_intent.write_bytes(original_sync)
            assert not (root / 'reminder_handoff_preparations').exists() or not list(
                (root / 'reminder_handoff_preparations').glob('*.intent.json'))
            crashed = launch('provision-crash')
            assert crashed.returncode == 74, crashed.stderr + crashed.stdout
            intents = list((root / 'reminder_handoff_preparations').glob('*.intent.json'))
            assert len(intents) == 1
            original_id = json.loads(intents[0].read_text())['operationId']
            intent = json.loads(intents[0].read_text())
            day_dir = root / 'reminder_receipts' / intent['day']
            assert day_dir.is_dir() and [p.name for p in day_dir.iterdir()] == ['reminders.sqlite3']
            assert (day_dir / 'reminders.sqlite3').stat().st_size == 0
            assert (root / 'reminder_handoff_preparations' / (original_id + '.directory.json')).is_file()
            retry = launch('fresh')
            assert json.loads(retry.stdout)['error'] == 'reminder_worker_original_outcome_unknown', retry.stderr
            # A different physical directory cannot inherit the pending intent.
            saved = day_dir.with_name(day_dir.name + '-saved')
            day_dir.rename(saved)
            day_dir.mkdir()
            foreign = launch(original_id)
            assert json.loads(foreign.stdout)['error'] == 'reminder_uncertainty_directory_unknown', foreign.stderr
            assert not list(day_dir.iterdir())
            day_dir.rmdir()
            saved.rename(day_dir)
            resumed = launch(original_id)
            assert resumed.returncode == 0, resumed.stderr
            result = json.loads(resumed.stdout)
            assert result['state'] == 'pending' and result['code'] == 'sender_proof_unavailable'
            assert result['preparationId'] == original_id and result['uncertainCount'] == 2
            assert result['readyForCutover'] is False
            if __CONFIGURED__:
                done = root / 'reminder_handoff_preparations' / (original_id + '.done.json')
                original_done = done.read_bytes()
                tampered = json.loads(original_done); tampered['schemaVersion'] = True
                done.write_text(json.dumps(tampered), encoding='utf-8')
                invalid = launch(original_id)
                assert json.loads(invalid.stdout)['error'] == 'reminder_uncertainty_receipt_invalid', invalid.stderr
                done.write_bytes(original_done)
            with offline_migration_profile() as target:
                rows = personal_affairs_service.get_personal_affairs_service().list_items(target.agent_id)['items']
                assert {r['itemId']: r['title'] for r in rows} == {'old': 'after', 'new': 'source', 'target-only': 'target'}
                from datetime import datetime, timezone
                day = datetime.now(timezone.utc).strftime('%Y%m%d')
                owner = 'assistant-' + hashlib.sha256(target.agent_id.encode()).hexdigest()
                with ReminderReceiptStore(root / 'reminder_receipts' / day, owner_id=owner, maximum=4096) as store:
                    for item in ('old', 'new'):
                        eid = 'reminder:' + day + ':' + hashlib.sha256(item.encode()).hexdigest()
                        assert store.get(eid)['state'] == 'pending' and not store.reserve(eid)['created']
            from core.assistant_runtime.prehost_recovery_verifier import held_prehost_recovery_verifier, delete_exact_recovery_marker
            from core.infrastructure.reminder_source_mutex import _try_digest
            with held_prehost_recovery_verifier(dispatch=dispatch, preview=preview, project_id='registered:1',
                                                revision=1, operation_id=primary_sync) as verify_original:
                proof = verify_original()
                assert proof['state'] == 'verified' and proof['operationId'] == primary_sync
                assert proof['unmanagedSenders'] == 'unknown' and proof['readyForCutover'] is False
                marker = work / 'registry.prehost-recovery.json'
                marker.write_text(json.dumps({'schemaVersion': 1, 'projectId':'registered:1', 'revision':1,
                                               'operationId': primary_sync}), encoding='utf-8')
                marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
                stat = marker.lstat()
                identity = {'device':str(stat.st_dev & 0xffffffff), 'inode':str(stat.st_ino), 'birthtimeNs':str(stat.st_birthtime_ns)}
                pending = marker.with_name(marker.name + '.commit-pending')
                pending.write_text(json.dumps({'schemaVersion':1, 'projectId':'registered:1', 'revision':1, 'operationId':primary_sync,
                                               'markerSha256':marker_hash, 'state':'pending'}), encoding='utf-8')
                revoked = marker.with_name(marker.name + '.revoked')
                revoked.write_text('{}', encoding='utf-8')
                key = hashlib.sha256(('Vibelution.PrehostCommit.v1\0' + marker_hash).encode('ascii')).hexdigest()
                commit = _try_digest(key)
                assert commit is not None and not commit.abandoned
                try:
                    try:
                        delete_exact_recovery_marker(path=marker, expected_sha256=marker_hash,
                            expected_identity=identity, operation_id=primary_sync, commit_key=key,
                            commit_mutex=commit, verifier=verify_original, before_delete=lambda: None)
                    except Exception: pass
                    else: raise AssertionError('revoked marker was deleted')
                    assert marker.exists() and pending.exists()
                    revoked.unlink()
                    delete_exact_recovery_marker(path=marker, expected_sha256=marker_hash,
                        expected_identity=identity, operation_id=primary_sync, commit_key=key,
                        commit_mutex=commit, verifier=verify_original, before_delete=lambda: None)
                    assert not marker.exists() and pending.exists()
                finally:
                    commit.release()
            try: verify_original()
            except Exception: pass
            else: raise AssertionError('released verifier continued to certify')
            # Exercise the actual private child over a one-use loopback capability.
            import http.server, threading
            target_config = root / ('.initial-migration-models-v1-' + handoff_id('registered:1') + '-' + template['registryDigest'] + '.toml')
            assert not target_config.exists()
            capability = 'b' * 64
            binding = {'schemaVersion': 1, 'registeredProjectId': 'registered:1', 'revision': 1,
                'projectRoot': str(project), 'sourceConfig': str(config),
                'sourceProjectsHome': os.environ['VIBELUTION_PROJECTS_HOME'],
                'sourceUserProfile': os.environ['USERPROFILE'],
                'targetProfile': str(root), 'targetConfig': str(target_config),
                'syncId': primary_sync, 'mode': 'resume', 'recoveryId': None}
            class Handler(http.server.BaseHTTPRequestHandler):
                permits = 0
                def log_message(self, *args): pass
                def respond(self, value):
                    data = json.dumps(value).encode()
                    self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
                def do_GET(self):
                    assert self.headers['Authorization'] == 'Bearer ' + capability
                    if self.path == '/binding': self.respond(binding)
                    elif self.path == '/check': self.respond({'schemaVersion': 1, 'current': True})
                    else: raise AssertionError('invalid path')
                def do_POST(self):
                    assert self.headers['Authorization'] == 'Bearer ' + capability and self.path == '/permit'
                    assert self.rfile.read(int(self.headers['Content-Length'])) == b'{}'
                    Handler.permits += 1
                    self.respond({'schemaVersion': 1, 'granted': True})
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = os.environ.copy()
            env['VIBELUTION_REMINDER_WORKER_TOKEN'] = capability
            env['VIBELUTION_REMINDER_WORKER_URL'] = 'http://127.0.0.1:' + str(server.server_port)
            try:
                child = subprocess.run([sys.executable, '-B', 'scripts/assistant_reminder_offline_worker.py'],
                    cwd=Path.cwd(), env=env, capture_output=True, text=True, timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                server.shutdown(); server.server_close(); thread.join()
            assert child.returncode == 0, child.stdout + child.stderr
            assert target_config.is_file()
            assert Handler.permits == 1
            bridge_result = json.loads(child.stdout)
            assert bridge_result['syncId'] == primary_sync and bridge_result['state'] == 'pending'
            assert bridge_result['readyForCutover'] is False
            # Real Electron main, real registry lease, native captured Job and
            # private Python child; a second Job resumes the original ID.
            repo = Path.cwd()
            electron_dir = repo / 'desktop/electron'
            addon = electron_dir / 'dist/native/workbench_job.node'
            electron = electron_dir / 'node_modules/electron/dist/electron.exe'
            fixture = work / 'electron-worker'
            fixture.mkdir()
            (fixture / 'package.json').write_text('{"name":"reminder-worker-fixture","version":"1.0.0","type":"module","main":"main.mjs"}')
            program = textwrap.dedent(r"""
                import { app } from 'electron';
                import { createHash } from 'node:crypto';
                import { spawnSync } from 'node:child_process';
                import { createRequire } from 'node:module';
                import { join } from 'node:path';
                import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
                import { AssistantProjectRegistryConnection } from __REGISTRY__;
                import { runReminderOfflineJob } from __JOB__;
                import { ProjectAdmission } from __ADMISSION__;
                import { startPrehostRecoveryJob } from __RECOVERY_JOB__;
                app.setPath('userData', join(process.env.FIXTURE_ROOT, 'electron-data'));
                app.disableHardwareAcceleration();
                app.whenReady().then(async () => {
                  const native = createRequire(import.meta.url)(process.env.FIXTURE_ADDON);
                  const connection = new AssistantProjectRegistryConnection(join(process.env.FIXTURE_ROOT, 'registry.json'));
                  const admission = new ProjectAdmission();
                  await connection.reconcile({schemaVersion:1,integrationRoot:process.env.FIXTURE_PROJECT,
                    items:[{id:'fixture',path:process.env.FIXTURE_PROJECT,checkedOut:true}]});
                  const projectId = Object.keys(connection.snapshot().projects)[0];
                  const digest = value => createHash('sha256').update(value).digest('hex');
                  const operationId='initial-'+digest(projectId+':reminder_handoff').slice(0,40);
                  const electronSync='affairs-'+digest(projectId+':reminder_handoff').slice(0,40);
                  const handoff={...JSON.parse(process.env.FIXTURE_HANDOFF_TEMPLATE),registeredProjectId:projectId,
                    operationId,syncId:electronSync,revision:connection.snapshot().revision};
                  const targetConfig=join(process.env.FIXTURE_TARGET,'.initial-migration-models-v1-'+operationId+'-'+handoff.registryDigest+'.toml');
                  const handoffDir=join(process.env.FIXTURE_TARGET,'reminder_handoff_intents',digest(operationId));
                  mkdirSync(handoffDir,{recursive:true});writeFileSync(join(handoffDir,'intent.json'),JSON.stringify(handoff));
                  const registeredRoot = connection.snapshot().projects[projectId];
                  if (registeredRoot === process.env.FIXTURE_PROJECT ||
                      registeredRoot.toLowerCase() !== process.env.FIXTURE_PROJECT.toLowerCase())
                    throw Error('fixture did not exercise case-variant source identity');
                  const run = mode => connection.withPreHostSource(projectId, async lease => {
                    let running;
                    const projectSeal = admission.seal(lease.registration.root, { drainOnRevoke: async () => { await running; } });
                    running = runReminderOfflineJob({
                    sourceRoot:process.env.FIXTURE_REPO,pythonPath:process.env.FIXTURE_PYTHON,pythonArguments:[],
                    runtimeRoot:join(process.env.FIXTURE_ROOT,'jobs'),env:process.env,native,lease,projectSeal,
                    binding:{registeredProjectId:projectId,sourceConfig:process.env.FIXTURE_SOURCE_CONFIG,
                      sourceProjectsHome:process.env.FIXTURE_PROJECTS_HOME,targetProfile:process.env.FIXTURE_TARGET,
                      targetConfig,syncId:electronSync,
                      mode,recoveryId:null}});
                    try { return await running; } finally { projectSeal.release(); await new Promise(resolve=>setImmediate(resolve)); }
                  }, {operationId:electronSync,receiptConfirmed:result=>result.state==='pending'&&typeof result.preparationId==='string'});
                  const first=await run('start'), second=await run('resume');
                  if(first.state!=='pending'||second.state!=='pending'||first.readyForCutover!==false||
                     second.preparationId!==first.preparationId) throw Error('worker result mismatch '+JSON.stringify({first,second})+
                       readdirSync(join(process.env.FIXTURE_ROOT,'jobs')).map(x=>readFileSync(join(process.env.FIXTURE_ROOT,'jobs',x,'stderr.log'),'utf8')).join('\n'));
                  // The original source/target locks stay in one recovery Job
                  // while main checks the receipt and commits an exact marker.
                  let recoveryLease;
                  const recoverySeal=admission.seal(connection.registration(projectId).root,
                    {drainOnRevoke:async()=>{if(recoveryLease) await recoveryLease.release();}});
                  const registration=connection.registration(projectId), physical=statSync(registration.root,{bigint:true});
                  const recoveryMarker={schemaVersion:1,projectId,operationId:electronSync,revision:connection.snapshot().revision,
                    registration,identity:{dev:String(physical.dev),ino:String(physical.ino),birthtimeNs:String(physical.birthtimeNs)}};
                  recoveryLease=await startPrehostRecoveryJob({marker:recoveryMarker,sourceRoot:process.env.FIXTURE_REPO,
                    pythonPath:process.env.FIXTURE_PYTHON,pythonArguments:[],runtimeRoot:join(process.env.FIXTURE_ROOT,'jobs'),
                    sourceConfig:process.env.FIXTURE_SOURCE_CONFIG,sourceProjectsHome:process.env.FIXTURE_PROJECTS_HOME,
                    targetProfile:process.env.FIXTURE_TARGET,
                    env:process.env,projectSeal:recoverySeal,native});
                  if(!recoveryLease||!await recoveryLease.check()||!await recoveryLease.verifyReceipt()) throw Error('held verifier unavailable');
                  const markerPath=join(process.env.FIXTURE_ROOT,'fixture.prehost-recovery.json');
                  writeFileSync(markerPath,JSON.stringify(recoveryMarker));
                  const markerSha256=digest(readFileSync(markerPath));
                  const file=statSync(markerPath,{bigint:true});
                  const markerIdentity={device:String(file.dev),inode:String(file.ino),birthtimeNs:String(file.birthtimeNs)};
                  const commitKey=digest('Vibelution.PrehostCommit.v1\0'+markerSha256);
                  writeFileSync(markerPath+'.commit-pending',JSON.stringify({schemaVersion:1,projectId,revision:recoveryMarker.revision,
                    operationId:electronSync,markerSha256,state:'pending'}));
                  if(!await recoveryLease.commitMarker({markerPath,markerSha256,markerIdentity,commitKey,checkAuthority:()=>recoverySeal.check()}))
                    throw Error('held marker commit unavailable '+readdirSync(join(process.env.FIXTURE_ROOT,'jobs')).map(x=>readFileSync(join(process.env.FIXTURE_ROOT,'jobs',x,'stderr.log'),'utf8')).join('\n'));
                  if(existsSync(markerPath)||!existsSync(markerPath+'.commit-pending')) throw Error('marker commit evidence missing');
                  await recoveryLease.release();recoverySeal.release();await new Promise(resolve=>setImmediate(resolve));
                  // Revoke while an admitted real child is paused at its next
                  // private checkpoint. The unbound producer must wait for
                  // that exact Job's natural exit and both output drains.
                  await connection.withPreHostSource(projectId, async lease => {
                    let running, entered=false, terminations=0;
                    const projectSeal=admission.seal(lease.registration.root,{drainOnRevoke:async()=>{await running;}});
                    const mark=join(process.env.FIXTURE_TARGET,'test-checkpoint'), resume=join(process.env.FIXTURE_TARGET,'test-resume');
                    const python=`import os,sys,time,runpy\nimport scripts.assistant_migration_activate as m\noriginal=m._initial_call\ndef held(c,t,method,path):\n if path=='/check' and not os.path.exists(${JSON.stringify(mark)}):\n  open(${JSON.stringify(mark)},'w').close()\n  while not os.path.exists(${JSON.stringify(resume)}): time.sleep(.025)\n return original(c,t,method,path)\nm._initial_call=held\nentry=sys.argv[1]\nsys.argv=[entry]\nrunpy.run_path(entry,run_name='__main__')`;
                    const tracked={spawn:(x)=>native.spawn(x), activeCount:(x)=>native.activeCount(x),
                      exitCode:(x)=>native.exitCode(x),drainStatus:(x)=>native.drainStatus(x),
                      terminate:(x)=>{terminations++;return native.terminate(x);},close:(x)=>native.close(x)};
                    running=runReminderOfflineJob({sourceRoot:process.env.FIXTURE_REPO,pythonPath:process.env.FIXTURE_PYTHON,
                      pythonArguments:['-c',python],runtimeRoot:join(process.env.FIXTURE_ROOT,'jobs'),env:process.env,
                      native:tracked,lease,projectSeal,binding:{registeredProjectId:projectId,sourceConfig:process.env.FIXTURE_SOURCE_CONFIG,
                        sourceProjectsHome:process.env.FIXTURE_PROJECTS_HOME,targetProfile:process.env.FIXTURE_TARGET,
                        targetConfig,syncId:electronSync,mode:'resume',recoveryId:null}});
                    const deadline=Date.now()+12000;
                    while(!existsSync(mark)&&Date.now()<deadline) await new Promise(r=>setTimeout(r,25));
                    if(!existsSync(mark)) throw Error('worker checkpoint unavailable');
                    const gateProbe = () => spawnSync(process.env.FIXTURE_PYTHON,['-B','-c',
                      'from pathlib import Path\nfrom core.infrastructure.reminder_route_gate import route_writer_gate\nimport sys\ntry:\n with route_writer_gate(Path(sys.argv[1]),required=True): sys.exit(2)\nexcept Exception: sys.exit(0)',
                      process.env.FIXTURE_PROJECT],{cwd:process.env.FIXTURE_REPO,env:process.env,windowsHide:true,timeout:10000});
                    const busyProbe=gateProbe();
                    if(busyProbe.status!==0) throw Error('worker did not hold cross-process route gate: '+String(busyProbe.stderr));
                    const newcomer=admission.observe(()=>{throw Error('unknown source');},async()=>{entered=true;});
                    await new Promise(r=>setTimeout(r,150));
                    if(entered||!projectSeal.signal.aborted) throw Error('new producer entered before job drained');
                    writeFileSync(resume,'resume');
                    const result=await running; await newcomer;
                    if(result.state!=='unknown'||!entered||terminations!==0) throw Error('revocation did not drain naturally');
                    const freeProbe=gateProbe();
                    if(freeProbe.status!==2) throw Error('worker route gate was not released after exit: '+String(freeProbe.stderr));
                  }, {operationId:electronSync,receiptConfirmed:()=>false});
                  process.stdout.write(JSON.stringify({first,second,electronSync,projectId}));app.exit(0);
                }).catch(error => {process.stderr.write(String(error&&error.stack||error));app.exit(1);});
            """).replace('__REGISTRY__', json.dumps(str(electron_dir / 'src/assistant/projectRegistryConnection.ts'))).replace(
                '__JOB__', json.dumps(str(electron_dir / 'src/assistant/reminderOfflineJob.ts'))).replace(
                '__ADMISSION__', json.dumps(str(electron_dir / 'src/lifecycle/projectAdmission.ts'))).replace(
                '__RECOVERY_JOB__', json.dumps(str(electron_dir / 'src/assistant/prehostRecoveryJob.ts')))
            (fixture / 'main.ts').write_text(program, encoding='utf-8')
            node = shutil.which('node')
            build_code = "require('esbuild').buildSync({entryPoints:[process.argv[1]],outfile:process.argv[2],bundle:true,platform:'node',format:'esm',external:['electron'],logLevel:'silent'})"
            build = subprocess.run([node, '-e', build_code, str(fixture / 'main.ts'), str(fixture / 'main.mjs')],
                cwd=electron_dir, env=os.environ.copy(), capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
            assert build.returncode == 0, build.stderr
            env = os.environ.copy()
            env.pop('ELECTRON_RUN_AS_NODE', None)
            env.update({'FIXTURE_ROOT':str(fixture), 'FIXTURE_ADDON':str(addon), 'FIXTURE_PROJECT':str(project),
                'FIXTURE_REPO':str(repo), 'FIXTURE_PYTHON':sys.executable, 'FIXTURE_SOURCE_CONFIG':str(config),
                'FIXTURE_PROJECTS_HOME':os.environ['VIBELUTION_PROJECTS_HOME'], 'FIXTURE_TARGET':str(root),
                'FIXTURE_HANDOFF_TEMPLATE':json.dumps(template)})
            electron_result = subprocess.run([str(electron), str(fixture), '--disable-gpu'], cwd=electron_dir,
                env=env, capture_output=True, text=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            assert electron_result.returncode == 0, electron_result.stderr + electron_result.stdout
            result = json.loads(electron_result.stdout)
            assert result['first']['preparationId'] == result['second']['preparationId']
            electron_sync = result['electronSync']
            final_claim = root / 'reminder_offline_operations' / (hashlib.sha256(electron_sync.encode()).hexdigest() + '.intent.json')
            assert json.loads(final_claim.read_text())['baselineId'] == primary_sync
            write_handoff('registered:second')
            lost_sync = launch('sync-intent', baseline=electron_sync, sync=sync_id('registered:second'), registration='registered:second')
            assert lost_sync.returncode == 77, lost_sync.stderr + lost_sync.stdout
            unknown_sync = launch('resume', baseline=electron_sync, sync=sync_id('registered:second'), registration='registered:second')
            assert json.loads(unknown_sync.stdout)['error'] == 'affairs_sync_outcome_unknown', unknown_sync.stderr
            # Divergent edits to the same existing item must remain a pending
            # conflict, including on confirmation-only recovery of this ID.
            # Isolate this scenario from the deliberately interrupted sync
            # above, which correctly blocks all later baseline discovery.
            lost_record = root / 'affairs_conflicts' / (hashlib.sha256(sync_id('registered:second').encode()).hexdigest() + '.json')
            saved_lost_record = lost_record.read_bytes()
            lost_record.unlink()
            with offline_migration_profile() as target:
                personal_affairs_service.get_personal_affairs_service().store.write_jsonl(
                    target.agent_id, 'affairs/items.jsonl',
                    [row('old', 'target changed'), row('new', 'source'), row('target-only', 'target')])
            ledger.write_bytes(raw([row('old', 'source changed'), row('new', 'source')]))
            write_handoff('registered:conflict')
            conflict_sync = sync_id('registered:conflict')
            conflict = launch('fresh', sync=conflict_sync, registration='registered:conflict')
            conflict_result = json.loads(conflict.stdout)
            assert conflict_result.get('state') == 'pending' and conflict_result.get('code') == 'affairs_conflicts', conflict.stdout + conflict.stderr
            assert conflict_result['conflictCount'] > 0 and conflict_result['readyForCutover'] is False
            conflict_resume = launch('resume', sync=conflict_sync, registration='registered:conflict')
            assert json.loads(conflict_resume.stdout).get('code') == 'affairs_conflicts', conflict_resume.stdout + conflict_resume.stderr
            lost_record.write_bytes(saved_lost_record)
            original_handoff = __import__('core.assistant_runtime.reminder_handoff_intent', fromlist=['read_handoff_intent']).read_handoff_intent(root, result['projectId'])
            snapshot = root / ('.initial-migration-models-v1-' + original_handoff['operationId'] + '-' + original_handoff['registryDigest'] + '.toml')
            saved_snapshot = snapshot.read_bytes()
            original_config = config.read_text(encoding='utf-8')
            updated_config = original_config.replace('[llm.providers.local.models.test]', '[llm.providers.local.models.other]').replace('model_ref = "local/test"', 'model_ref = "local/other"')
            assert updated_config != original_config
            config.write_text(updated_config, encoding='utf-8')
            changed_dispatch = DispatchService(root, {})
            changed_dispatch.replace_projects({'schemaVersion':1, 'revision':1, 'projects':{result['projectId']:str(project)}})
            changed_preview = HistoryPreview(changed_dispatch, config)
            try:
                with held_prehost_recovery_verifier(dispatch=changed_dispatch, preview=changed_preview, project_id=result['projectId'],
                                                    revision=1, operation_id=electron_sync) as check:
                    check()
            except Exception: pass
            else: raise AssertionError('changed original source authority was accepted')
            assert snapshot.read_bytes() == saved_snapshot
    ''').replace('__CONFIGURED__', repr(configured)), config_text=TEST_MODEL_CONFIG)
