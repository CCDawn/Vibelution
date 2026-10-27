"""Online lease primitives only; no host or model action is installed here."""

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_online_lease_is_scoped_to_a_live_generation_turn_and_existing_baseline(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os, threading
        from contextlib import contextmanager
        from pathlib import Path
        from core.assistant_runtime import (native, migration_affairs, migration_episodic,
            migration_knowledge, migration_affairs_conflicts, migration_affairs_sync)
        from core.web.services import personal_affairs_service
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.assistant_runtime.online_affairs_sync_lease import OnlineAffairsSyncOwner, check_affairs_sync_lease
        from core.assistant_runtime.reminders import LauncherReminders
        from core.assistant_runtime.reminder_receipts import ReminderReceiptError

        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        assistant = native.bootstrap(root)['assistant']
        scope = {'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'}
        row = {'schemaVersion': 1, 'itemId': 'item', 'kind': 'todo', 'title': 'fixture',
               'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        raw = json.dumps(row).encode() + b'\n'
        digest = hashlib.sha256(raw).hexdigest()
        archive = root / 'history_sources/migrations/initial'
        source = archive / 'sources/mps-ref/affairs/items.jsonl'
        source.parent.mkdir(parents=True)
        source.write_bytes(raw)
        (archive / 'manifest.json').write_text(json.dumps({
            'schemaVersion': 2, 'migrationId': 'initial', 'sourceScope': scope,
            'readOnly': True, 'untrustedContent': True, 'entries': [{
                'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
        (archive / '.confirmed').mkdir()
        receipts = root / 'affairs_migrations'
        receipts.mkdir()
        receipt = receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')
        receipt.write_text(json.dumps({'schemaVersion': 1, 'migrationId': 'initial',
            'sourceScope': scope, 'sourceSha256': digest, 'targetAgentId': assistant['agentId'],
            'itemCount': 1, 'published': True}))

        # Test double only: real host wiring must supply the guarded native
        # Turn/generation and approval checks before exposing any operation.
        @contextmanager
        def guard(generation, turn):
            assert (generation, turn) == ('host-generation', 'turn-current')
            yield
        owner = OnlineAffairsSyncOwner('host-generation', guard)
        args = dict(generation='host-generation', turn_id='turn-current',
                    baseline_migration_id='initial', source_scope=scope)
        try:
            with owner.admit(**args) as lease:
                assert lease.agent_id == assistant['agentId']
                assert lease.session_id == assistant['directSessionId']
                check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id='initial')
                for kwargs in ({}, {'source_scope': {**scope, 'agentId': 'other'},
                                    'baseline_migration_id': 'initial'},
                               {'source_scope': scope, 'baseline_migration_id': 'other'}):
                    try: check_affairs_sync_lease(lease, **kwargs)
                    except MigrationIOError: pass
                    else: raise AssertionError('unbound authority accepted')
                # The legacy shared checks remain offline-only, including
                # first import, reminder preview, episodic and knowledge.
                for check in (migration_affairs._check_lease, migration_episodic._check_lease,
                              migration_knowledge._lease):
                    try: check(lease)
                    except MigrationIOError: pass
                    else: raise AssertionError('online lease escaped its capability')
                reminders = LauncherReminders(root, lease.agent_id)
                try: reminders.next()
                except ReminderReceiptError as error: assert str(error) == 'reminder_imported_profile_blocked'
                else: raise AssertionError('imported profile emitted a reminder')
                # Exercise the real prepare/reconcile functions with their
                # future call-site checker injected only in this test. Product
                # wiring is intentionally not installed by this module.
                latest = root / 'history_sources/migrations/latest'
                latest_source = latest / 'sources/mps-ref/affairs/items.jsonl'
                latest_source.parent.mkdir(parents=True)
                latest_raw = json.dumps({**row, 'title': 'updated'}).encode() + b'\n'
                latest_source.write_bytes(latest_raw)
                (latest / 'manifest.json').write_text(json.dumps({
                    'schemaVersion': 2, 'migrationId': 'latest', 'sourceScope': scope,
                    'readOnly': True, 'untrustedContent': True, 'entries': [{
                        'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                        'path': 'sources/mps-ref/affairs/items.jsonl',
                        'sha256': hashlib.sha256(latest_raw).hexdigest(), 'size': len(latest_raw)}]}))
                (latest / '.confirmed').mkdir()
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [row])
                migration_affairs_conflicts.prepare_affairs_conflicts(lease,
                    baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='online-test', source_scope=scope)
                result = migration_affairs_sync.reconcile_affairs(lease,
                    sync_id='online-test', source_scope=scope)
                assert result['appliedCount'] == 1 and result['conflictCount'] == 0
                assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl')[0]['title'] == 'updated'
                failures = []
                def other_thread():
                    try: check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id='initial')
                    except MigrationIOError: failures.append('thread')
                    try:
                        with owner.admit(**args): pass
                    except MigrationIOError: failures.append('busy')
                worker = threading.Thread(target=other_thread)
                worker.start(); worker.join(timeout=5)
                assert not worker.is_alive() and failures == ['thread', 'busy']
                assert owner.revoke() is False
                try: check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id='initial')
                except MigrationIOError: pass
                else: raise AssertionError('revoked lease accepted')
            assert owner.drained()
            try:
                with owner.admit(**args): pass
            except MigrationIOError: pass
            else: raise AssertionError('revoked owner reopened')
            # A native shutdown signals stop before waiting on the native
            # lock; the active lease notices it and drains without deadlock.
            owner2 = OnlineAffairsSyncOwner('host-generation', guard)
            shutdown_result = []
            with owner2.admit(**args) as lease2:
                worker = threading.Thread(target=lambda: shutdown_result.append(native.shutdown(timeout=5)))
                worker.start()
                assert native._STOP_REQUESTED.wait(timeout=3)
                try: check_affairs_sync_lease(lease2, source_scope=scope, baseline_migration_id='initial')
                except MigrationIOError: pass
                else: raise AssertionError('stopping native accepted')
            worker.join(timeout=7)
            assert not worker.is_alive() and shutdown_result[0]['closed'] and owner2.drained()
        finally:
            assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)


def test_online_lease_rejects_missing_baseline_and_never_waits_for_native_shutdown_lock(tmp_path):
    _run(tmp_path, r'''
        import os, threading
        from contextlib import contextmanager
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.assistant_runtime.online_affairs_sync_lease import OnlineAffairsSyncOwner
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        native.bootstrap(root)
        @contextmanager
        def guard(generation, turn):
            yield
        owner = OnlineAffairsSyncOwner('generation', guard)
        args = dict(generation='generation', turn_id='turn', baseline_migration_id='missing',
                    source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'})
        try:
            try:
                with owner.admit(**args): pass
            except MigrationIOError: pass
            else: raise AssertionError('missing initial import accepted')
            assert owner.drained()
            acquired, release = threading.Event(), threading.Event()
            def lock_native():
                with native._LOCK:
                    acquired.set()
                    assert release.wait(timeout=5)
            worker = threading.Thread(target=lock_native)
            worker.start(); assert acquired.wait(timeout=5)
            try:
                try:
                    with owner.admit(**args): pass
                except MigrationIOError as error: assert str(error) == 'online_affairs_sync_busy'
                else: raise AssertionError('native lock unexpectedly admitted')
            finally:
                release.set(); worker.join(timeout=5)
            assert not worker.is_alive() and owner.drained()
        finally:
            assert native.shutdown()['closed']
    ''', config_text=TEST_MODEL_CONFIG)
