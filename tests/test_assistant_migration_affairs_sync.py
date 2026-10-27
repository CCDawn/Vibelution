"""Synthetic three-way sync through the native affairs store and offline lease."""
import pytest
import textwrap
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


@pytest.mark.parametrize('case', ['published', 'missing', 'uncertain'])
def test_final_sync_preserves_target_edits_and_recovers_after_publication(tmp_path, case):
    _run(tmp_path, 'CASE = ' + repr(case) + '\n' + textwrap.dedent(r'''
        import hashlib, json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_affairs_conflicts import prepare_affairs_conflicts
        from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
        from core.assistant_runtime import migration_affairs_sync as sync
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.affairs_conflict_actions import _sync_receipt_status
        from core.web.services import personal_affairs_service
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        identity = native.bootstrap(root)['assistant']
        assert native.shutdown()['closed']
        scope = {'projectId': 'project', 'instanceId': 'instance', 'agentId': 'old-pa'}
        def row(item_id, title):
            return {'schemaVersion': 1, 'itemId': item_id, 'kind': 'todo', 'title': title,
                    'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        old = [row('changed', 'before'), row('removed', 'before'), row('conflict', 'before')]
        new = [row('changed', 'after'), row('added', 'new'), row('conflict', 'source')]
        def archive(mid, rows):
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            digest = hashlib.sha256(raw).hexdigest()
            base = root / 'history_sources/migrations' / mid
            source = base / 'sources/mps-ref/affairs/items.jsonl'
            source.parent.mkdir(parents=True)
            source.write_bytes(raw)
            (base / 'manifest.json').write_text(json.dumps({
                'schemaVersion': 1, 'migrationId': mid, 'sourceScope': scope,
                'readOnly': True, 'untrustedContent': True, 'entries': [{
                    'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                    'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
            (base / '.confirmed').mkdir()
            return digest
        old_hash = archive('initial', old)
        archive('latest', new)
        receipts = root / 'affairs_migrations'
        receipts.mkdir()
        (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
            'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
            'sourceSha256': old_hash, 'targetAgentId': identity['agentId'],
            'itemCount': len(old), 'published': True}))
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            target = [old[0], old[1], row('conflict', 'user edit'), row('user-only', 'keep')]
            if CASE == 'missing':
                target = [row for row in target if row['itemId'] != 'removed']
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', target)
            prepare_affairs_conflicts(lease, baseline_migration_id='initial',
                snapshot_migration_id='latest', sync_id='final', source_scope=scope)
            assert _sync_receipt_status(root, 'unknown-id', lease.agent_id)['state'] == 'unknown'
            assert _sync_receipt_status(root, 'latest', lease.agent_id)['state'] == 'archived'
            assert _sync_receipt_status(root, 'final', lease.agent_id)['state'] == 'prepared'
            original = sync._replace_ledger
            if CASE == 'published':
                # Crash after the real ledger publication and confirm by readback.
                def interrupt(*args, **kwargs):
                    original(*args, **kwargs)
                    raise RuntimeError('synthetic interruption')
                sync._replace_ledger = interrupt
                try:
                    try: reconcile_affairs(lease, sync_id='final', source_scope=scope)
                    except RuntimeError: pass
                    else: raise AssertionError('interruption not injected')
                finally: sync._replace_ledger = original
                assert _sync_receipt_status(root, 'final', lease.agent_id)['state'] == 'pending'
                recovered = reconcile_affairs(lease, sync_id='final', source_scope=scope)
                assert recovered['reused'] and recovered['appliedCount'] == 2 and recovered['conflictCount'] == 2
                assert not recovered['readyForCutover'] and not recovered['sourceQuiesced']
                assert _sync_receipt_status(root, 'final', lease.agent_id)['state'] == 'published'
                rows = service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl')
                assert {r['itemId']: r['title'] for r in rows} == {
                    'changed': 'after', 'added': 'new', 'removed': 'before',
                    'conflict': 'user edit', 'user-only': 'keep'}
                rows[0]['title'] = 'later user edit'
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', rows)
                assert reconcile_affairs(lease, sync_id='final', source_scope=scope)['reused']
                assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl') == rows
            elif CASE == 'missing':
                missing = reconcile_affairs(lease, sync_id='final', source_scope=scope)
                assert missing['conflictCount'] == 2
                from core.assistant_runtime.migration_affairs_conflicts import list_affairs_conflicts
                changes = list_affairs_conflicts(root, sync_id='final', source_scope=scope,
                    target_agent_id=lease.agent_id, limit=12)['conflicts']
                assert next(item for item in changes if item['kind'] == 'removed')['syncStatus'] == 'unresolved'
            else:
                # An interruption before writing cannot safely be replayed.
                def interrupt_before(*args, **kwargs):
                    raise RuntimeError('synthetic interruption before write')
                sync._replace_ledger = interrupt_before
                try:
                    try: reconcile_affairs(lease, sync_id='final', source_scope=scope)
                    except RuntimeError: pass
                    else: raise AssertionError('interruption not injected')
                finally: sync._replace_ledger = original
                try: reconcile_affairs(lease, sync_id='final', source_scope=scope)
                except MigrationIOError as error: assert str(error) == 'affairs_sync_outcome_unknown'
                else: raise AssertionError('uncertain write was replayed')
                assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl') == target
    '''), config_text=TEST_MODEL_CONFIG)
