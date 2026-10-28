"""Real native target, source mutex, sync receipt and SQLite suppression."""
import textwrap

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_source_due_items_remain_visible_and_are_unknown_not_replayed(tmp_path):
    _run(tmp_path, textwrap.dedent(r'''
        import hashlib, json, os, shutil, subprocess, sys, textwrap
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.dispatch import DispatchService
        from core.assistant_runtime.history_preview import HistoryPreview
        from core.assistant_runtime.migration_affairs_conflicts import prepare_affairs_conflicts
        from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.reminder_receipts import ReminderReceiptStore
        from core.assistant_runtime.reminder_source_identity import observe_reminder_source
        from core.assistant_runtime.reminder_uncertain_preparation import prepare_current_day_uncertainty, inspect_uncertainty_preparation
        from core.assistant_runtime import reminder_uncertain_preparation as preparation
        from core.assistant_runtime.initial_migration_binding import _directory
        from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
        from core.web.services import personal_affairs_service
        from tests.test_assistant_migration_history import source, write_json
        from vibelution_storage import resolve_active_project_storage_paths

        work = Path(os.environ['ASSISTANT_TEST_WRITE_ROOT'])
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = source(work / 'fixture-source')
        project = workspace.parent.resolve()
        write_json(project / '.vibelution/project.json', {'schemaVersion': 1, 'projectId': 'source-project'})
        data = json.loads((workspace / 'agents/agents.json').read_text(encoding='utf-8'))
        data['agents'][0]['primaryMode'] = 'general'
        (workspace / 'agents/agents.json').write_text(json.dumps(data), encoding='utf-8')
        config = Path(os.environ['VIBELUTION_CONFIG_PATH'])
        active = resolve_active_project_storage_paths(project, config_path=config).data / 'workspace'
        shutil.copytree(workspace, active)
        dispatch = DispatchService(root, {})
        dispatch.replace_projects({'schemaVersion': 1, 'revision': 1, 'projects': {'registered:1': str(project)}})
        preview = HistoryPreview(dispatch, config)
        def row(item_id, title, due='2020-01-01T00:00:00Z'):
            return {'schemaVersion': 1, 'itemId': item_id, 'kind': 'todo', 'title': title,
                    'status': 'open', 'dueAt': due, 'createdAt': '2025-02-01T00:00:00Z'}
        done = {**row('completed-src', 'completed source'), 'status': 'done'}
        old = [row('shared', 'before'), row('no-due', 'no due', ''), done]
        new = [row('shared', 'after'), row('source-new', 'source due'), row('no-due', 'no due', ''), done]
        raw = lambda rows: b''.join(json.dumps(r).encode() + b'\n' for r in rows)
        ledger = project / 'agents/agent-pa/plugins/personal-affairs/affairs/items.jsonl'
        ledger.parent.mkdir(parents=True)
        ledger.write_bytes(raw(new))
        initial = native.bootstrap(root)['assistant']
        assert native.shutdown()['closed']
        with observe_reminder_source(dispatch, preview, 'registered:1', 1) as observed:
            preview_row = preview._previews[observed._token]
            paths = preview_row[5]
            scope = {'projectId': paths.project_id, 'instanceId': paths.instance_id, 'agentId': observed.agent_id}
            def archive(mid, rows):
                content = raw(rows)
                digest = hashlib.sha256(content).hexdigest()
                base = root / 'history_sources/migrations' / mid
                item = base / 'sources/mps-ref/affairs/items.jsonl'
                item.parent.mkdir(parents=True)
                item.write_bytes(content)
                (base / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'migrationId': mid,
                    'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
                    'sourceRef': 'mps-ref', 'category': 'personal_affairs', 'path': 'sources/mps-ref/affairs/items.jsonl',
                    'sha256': digest, 'size': len(content)}]}))
                (base / '.confirmed').mkdir()
                return digest
            old_hash = archive('initial', old)
            archive('latest', new)
            initial_receipts = root / 'affairs_migrations'
            initial_receipts.mkdir()
            (initial_receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
                'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope, 'sourceSha256': old_hash,
                'targetAgentId': initial['agentId'], 'itemCount': len(old), 'published': True}))
            with offline_migration_profile() as target:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(target.agent_id, 'affairs/items.jsonl', old + [row('target-only', 'independent')])
                prepare_affairs_conflicts(target, baseline_migration_id='initial', snapshot_migration_id='latest',
                                          sync_id='final', source_scope=scope)
                result = reconcile_affairs(target, sync_id='final', source_scope=scope)
                assert result['conflictCount'] == 0
                mutex = try_acquire_reminder_source_mutex(observed)
                assert mutex is not None
                try:
                    mutex.abandoned = True
                    try: prepare_current_day_uncertainty(source=observed, source_mutex=mutex, target=target, sync_id='final')
                    except MigrationIOError as error: assert str(error) == 'reminder_uncertainty_source_recovery_required'
                    else: raise AssertionError('abandoned mutex treated as proof')
                    mutex.abandoned = False
                finally:
                    mutex.release()
            # The first real process exits abruptly after persisting pending
            # evidence and before publishing its preparation receipt.
            recovery_code = textwrap.dedent(r"""
                import json, os, sys
                from pathlib import Path
                from core.assistant_runtime.dispatch import DispatchService
                from core.assistant_runtime.history_preview import HistoryPreview
                from core.assistant_runtime.migration_profile import offline_migration_profile
                from core.assistant_runtime.reminder_source_identity import observe_reminder_source
                from core.assistant_runtime.reminder_uncertain_preparation import prepare_current_day_uncertainty
                from core.assistant_runtime import reminder_uncertain_preparation as preparation
                from core.infrastructure.reminder_source_mutex import try_acquire_reminder_source_mutex
                root=Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
                dispatch=DispatchService(root,{})
                dispatch.replace_projects({'schemaVersion':1,'revision':1,'projects':{'registered:1':sys.argv[1]}})
                preview=HistoryPreview(dispatch,Path(os.environ['VIBELUTION_CONFIG_PATH']))
                with observe_reminder_source(dispatch,preview,'registered:1',1) as source:
                    mutex=try_acquire_reminder_source_mutex(source)
                    assert mutex is not None
                    try:
                        with offline_migration_profile() as target:
                            if sys.argv[2] == 'crash':
                                original=preparation.atomic_write_json
                                def interrupted(path,payload,**kwargs):
                                    if str(path).endswith('.done.json'): os._exit(73)
                                    return original(path,payload,**kwargs)
                                preparation.atomic_write_json=interrupted
                            result=prepare_current_day_uncertainty(source=source,source_mutex=mutex,target=target,sync_id='final',
                                recovery_id=None if sys.argv[2] == 'crash' else sys.argv[2])
                            print(json.dumps(result))
                    finally: mutex.release()
            """)
            crashed = subprocess.run([sys.executable, '-B', '-c', recovery_code, str(project), 'crash'],
                                     cwd=Path.cwd(), env=os.environ.copy(), capture_output=True, text=True,
                                     timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            assert crashed.returncode == 73, crashed.stderr
            intents = list((root / 'reminder_handoff_preparations').glob('*.intent.json'))
            assert len(intents) == 1
            original_intent = json.loads(intents[0].read_text(encoding='utf-8'))
            original_id = original_intent['operationId']
            assert original_intent['sourceAuthorityKey'] == observed._authority
            assert original_intent['targetDirectory'] == _directory(root)
            assert not (root / 'reminder_handoff_preparations' / (original_id + '.done.json')).exists()
            with offline_migration_profile() as target:
                pending = inspect_uncertainty_preparation(target=target, operation_id=original_id)
                assert pending['recordedState'] == 'pending' and pending['sourceState'] == 'unknown'
                assert pending['readyForCutover'] is False
            # A fresh process reacquires both locks and recovers exactly that ID.
            result = subprocess.run([sys.executable, '-B', '-c', recovery_code, str(project), original_id],
                                    cwd=Path.cwd(), env=os.environ.copy(), capture_output=True, text=True,
                                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0, result.stderr
            recovered = json.loads(result.stdout)
            assert recovered['operationId'] == original_id and recovered['state'] == 'prepared'
            assert recovered['uncertainCount'] == 4 and recovered['created'] == 0
            assert recovered['sourceQuiesced'] is False and recovered['readyForCutover'] is False
            with offline_migration_profile() as target:
                service = personal_affairs_service.get_personal_affairs_service()
                status = inspect_uncertainty_preparation(target=target, operation_id=original_id)
                assert status['recordedState'] == 'prepared' and status['sourceState'] == 'unknown'
                assert status['readyForCutover'] is False
                mutex = try_acquire_reminder_source_mutex(observed)
                assert mutex is not None
                try:
                    repeated = prepare_current_day_uncertainty(source=observed, source_mutex=mutex, target=target,
                                                               sync_id='final', recovery_id=original_id)
                    assert repeated['operationId'] == original_id and repeated['uncertainCount'] == 4 and repeated['created'] == 0
                    class Tomorrow(datetime):
                        @classmethod
                        def now(cls, tz=None):
                            return datetime.now(tz) + timedelta(days=1)
                    preparation.datetime = Tomorrow
                    try:
                        next_day = prepare_current_day_uncertainty(source=observed, source_mutex=mutex, target=target,
                                                                   sync_id='final', recovery_id=original_id)
                        assert next_day['operationId'] == original_id and next_day['day'] == repeated['day']
                    finally:
                        preparation.datetime = datetime
                    visible = service.list_items(target.agent_id)['items']
                    assert {r['itemId'] for r in visible} == {'shared', 'source-new', 'no-due', 'completed-src', 'target-only'}
                    day = datetime.now(timezone.utc).strftime('%Y%m%d')
                    eid = lambda value: 'reminder:' + day + ':' + hashlib.sha256(value.encode()).hexdigest()
                    owner = 'assistant-' + hashlib.sha256(target.agent_id.encode()).hexdigest()
                    with ReminderReceiptStore(root / 'reminder_receipts' / day, owner_id=owner, maximum=4096) as store:
                        for item in ('shared', 'source-new', 'no-due', 'completed-src'):
                            assert store.get(eid(item))['state'] == 'pending'
                            assert store.reserve(eid(item))['created'] is False
                        assert store.get(eid('target-only')) is None
                        with store._transaction() as conn:
                            conn.execute('DELETE FROM reminder_receipts WHERE event_id=?', (eid('shared'),))
                    try:
                        prepare_current_day_uncertainty(source=observed, source_mutex=mutex, target=target,
                                                        sync_id='final', recovery_id=original_id)
                    except MigrationIOError as error:
                        assert str(error) == 'reminder_uncertainty_receipt_invalid'
                    else:
                        raise AssertionError('missing completed evidence silently recreated')
                    with ReminderReceiptStore(root / 'reminder_receipts' / day, owner_id=owner, maximum=4096) as store:
                        assert store.get(eid('shared')) is None
                    # Reopening an old completed affair must not re-notify it today.
                    assert service.reopen_item(target.agent_id, item_id='completed-src')['status'] == 'open'
                    with ReminderReceiptStore(root / 'reminder_receipts' / day, owner_id=owner, maximum=4096) as store:
                        assert store.reserve(eid('completed-src'))['created'] is False
                    # Later target edits make the prior sync receipt insufficient.
                    changed = service.store.read_jsonl(target.agent_id, 'affairs/items.jsonl')
                    changed[0]['title'] = 'later target edit'
                    service.store.write_jsonl(target.agent_id, 'affairs/items.jsonl', changed)
                    try: prepare_current_day_uncertainty(source=observed, source_mutex=mutex, target=target, sync_id='final')
                    except MigrationIOError as error: assert str(error) == 'reminder_uncertainty_sync_unconfirmed'
                    else: raise AssertionError('changed target accepted')
                finally:
                    mutex.release()
    '''), config_text=TEST_MODEL_CONFIG)
