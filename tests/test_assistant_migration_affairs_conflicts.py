"""Synthetic source archives and native target, no production data."""
import hashlib
import json

import pytest

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_bounded_chain_accepts_more_than_32_links_and_64_receipts_and_rejects_cycles(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_affairs_conflicts as owner
    from core.assistant_runtime.migration_io import MigrationIOError

    root = tmp_path
    scope = {'projectId': 'project', 'instanceId': 'instance', 'agentId': 'old-pa'}
    target = 'native-pa'
    def row(index):
        return {'schemaVersion': 1, 'itemId': 'one', 'kind': 'todo', 'title': 'v' + str(index),
                'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
    def archive(mid, index):
        raw = json.dumps(row(index)).encode() + b'\n'
        base = root / 'history_sources/migrations' / mid
        path = base / 'sources/mps-ref/affairs/items.jsonl'
        path.parent.mkdir(parents=True); path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        (base / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'migrationId': mid,
            'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
                'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
        (base / '.confirmed').mkdir()
        return digest
    hashes = {'initial': archive('initial', 0)}
    for i in range(1, 71):
        hashes[f'snapshot-{i}'] = archive(f'snapshot-{i}', i)
    initial = root / 'affairs_migrations'; initial.mkdir()
    (initial / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
        'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
        'sourceSha256': hashes['initial'], 'targetAgentId': target, 'itemCount': 1, 'published': True}))
    first = owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    assert first['baselineMigrationId'] == 'initial' and first['sourceSha256'] == hashes['initial']
    assert first['readOnly'] and not first['sourceQuiesced'] and not first['readyForCutover']
    initial_path = initial / (hashlib.sha256(b'initial').hexdigest() + '.json')
    saved_initial = initial_path.read_bytes()
    original_candidates = owner._sync_candidates
    reads = 0
    def mutate_during_final_check(*args):
        nonlocal reads
        reads += 1
        if reads == 2:
            changed = json.loads(saved_initial); changed['published'] = False
            initial_path.write_text(json.dumps(changed))
        return original_candidates(*args)
    with monkeypatch.context() as m:
        m.setattr(owner, '_sync_candidates', mutate_during_final_check)
        with pytest.raises(MigrationIOError):
            owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    initial_path.write_bytes(saved_initial)
    records = root / 'affairs_conflicts'; records.mkdir()
    receipts = root / 'affairs_sync_receipts'; receipts.mkdir()
    for i in range(1, 71):
        sync, before, after = f'sync-{i}', ('initial' if i == 1 else f'snapshot-{i-1}'), f'snapshot-{i}'
        conflict_id = owner._digest({'syncId': sync, 'sourceScope': scope, 'itemId': 'one', 'kind': 'changed'})
        record = {'schemaVersion': 1, 'syncId': sync, 'sourceScope': scope, 'targetAgentId': target,
                  'baselineMigrationId': before, 'snapshotMigrationId': after,
                  'baselineSha256': hashes[before], 'snapshotSha256': hashes[after],
                  'readOnly': True, 'untrustedContent': True,
                  'conflicts': [{'conflictId': conflict_id, 'itemId': 'one', 'kind': 'changed',
                                 'baseline': row(i-1), 'source': row(i), 'target': row(i-1), 'targetState': 'present'}]}
        record_path = owner._record_path(root, sync)
        record_path.write_text(json.dumps(record))
        record_path.with_name(record_path.name + '.lock').write_bytes(b'')
        receipt = {'schemaVersion': 1, 'syncId': sync, 'sourceScope': scope, 'targetAgentId': target,
                   'recordSha256': owner._digest(record), 'published': True, 'targetSha256': '0' * 64,
                   'appliedCount': 1, 'conflictCount': 0, 'decisions': [{'conflictId': conflict_id, 'status': 'applied'}]}
        receipt_path = receipts / (hashlib.sha256(sync.encode()).hexdigest() + '.json')
        receipt_path.write_text(json.dumps(receipt))
        receipt_path.with_name(receipt_path.name + '.lock').write_bytes(b'')
    assert owner._verified_baseline(root, 'snapshot-70', scope, target)[0] == [row(70)]
    assert owner.discover_affairs_conflicts(root, target_agent_id=target, limit=1)['total'] == 70
    before = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in root.rglob('*') if path.is_file()}
    latest = owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    assert latest['baselineMigrationId'] == 'snapshot-70' and latest['sourceSha256'] == hashes['snapshot-70']
    assert before == {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in root.rglob('*') if path.is_file()}
    last_path = receipts / (hashlib.sha256(b'sync-70').hexdigest() + '.json')
    saved = last_path.read_bytes(); receipt = json.loads(saved)
    last_path.unlink()
    with pytest.raises(MigrationIOError, match='affairs_baseline_pending'):
        owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    last_path.write_bytes(saved)
    last_path.write_text(json.dumps({**receipt, 'published': False}))
    with pytest.raises(MigrationIOError, match='affairs_baseline_pending'):
        owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    last_path.write_text(json.dumps({**receipt, 'appliedCount': 0, 'conflictCount': 1,
        'decisions': [{'conflictId': receipt['decisions'][0]['conflictId'], 'status': 'unresolved'}]}))
    with pytest.raises(MigrationIOError, match='affairs_baseline_unresolved'):
        owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    last_path.write_bytes(saved)
    second_hash = archive('initial-2', 0)
    second_receipt = initial / (hashlib.sha256(b'initial-2').hexdigest() + '.json')
    second_receipt.write_text(json.dumps({'schemaVersion': 1, 'migrationId': 'initial-2', 'sourceScope': scope,
        'sourceSha256': second_hash, 'targetAgentId': target, 'itemCount': 1, 'published': True}))
    with pytest.raises(MigrationIOError, match='affairs_baseline_ambiguous'):
        owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    second_receipt.unlink()
    for patch in ({'targetAgentId': 'other'}, {'sourceScope': {**scope, 'agentId': 'other'}},
                  {'published': False}, {'decisions': [{'conflictId': receipt['decisions'][0]['conflictId'], 'status': 'unresolved'}]}):
        last_path.write_text(json.dumps({**receipt, **patch}))
        with pytest.raises(MigrationIOError):
            owner._verified_baseline(root, 'snapshot-70', scope, target)
    last_path.write_bytes(saved)
    marker = root / 'history_sources/migrations/snapshot-70/.confirmed'
    marker.rmdir()
    with pytest.raises(MigrationIOError, match='affairs_conflict_archive_unconfirmed'):
        owner._verified_baseline(root, 'snapshot-70', scope, target)
    marker.mkdir()
    # Two independently published links naming the same source snapshot are
    # ambiguous even if each receipt is internally consistent.
    original = json.loads(owner._record_path(root, 'sync-70').read_text())
    duplicate = {**original, 'syncId': 'duplicate'}
    new_id = owner._digest({'syncId': 'duplicate', 'sourceScope': scope, 'itemId': 'one', 'kind': 'changed'})
    duplicate['conflicts'] = [{**original['conflicts'][0], 'conflictId': new_id}]
    duplicate_path = owner._record_path(root, 'duplicate'); duplicate_path.write_text(json.dumps(duplicate))
    duplicate_receipt = {**receipt, 'syncId': 'duplicate', 'recordSha256': owner._digest(duplicate),
                         'decisions': [{'conflictId': new_id, 'status': 'applied'}]}
    duplicate_receipt_path = receipts / (hashlib.sha256(b'duplicate').hexdigest() + '.json')
    duplicate_receipt_path.write_text(json.dumps(duplicate_receipt))
    with pytest.raises(MigrationIOError, match='affairs_conflict_baseline_unbound'):
        owner._verified_baseline(root, 'snapshot-70', scope, target)
    with pytest.raises(MigrationIOError):
        owner.discover_affairs_baseline(root, source_scope=scope, target_agent_id=target)
    duplicate_receipt_path.unlink(); duplicate_path.unlink()
    with monkeypatch.context() as m:
        m.setattr(owner, '_CHAIN_LIMIT', 32)
        with pytest.raises(MigrationIOError, match='affairs_conflict_baseline_chain_limit'):
            owner._verified_baseline(root, 'snapshot-70', scope, target)
    with monkeypatch.context() as m:
        m.setattr(owner, '_SYNC_RECORD_LIMIT', 64)
        with pytest.raises(MigrationIOError, match='affairs_sync_receipt_limit'):
            owner._verified_baseline(root, 'snapshot-70', scope, target)
    with monkeypatch.context() as m:
        m.setattr(owner, '_CHAIN_BYTE_LIMIT', 32)
        with pytest.raises(MigrationIOError, match='affairs_conflict_baseline_chain_limit'):
            owner._verified_baseline(root, 'snapshot-70', scope, target)
    # Rebind the first link to the last snapshot, with consistent hashes and
    # receipt, so rejection requires detecting the actual cycle.
    path = owner._record_path(root, 'sync-1'); record = json.loads(path.read_text())
    record['baselineMigrationId'] = 'snapshot-70'; record['baselineSha256'] = hashes['snapshot-70']
    record['conflicts'][0]['baseline'] = row(70)
    path.write_text(json.dumps(record))
    receipt_path = receipts / (hashlib.sha256(b'sync-1').hexdigest() + '.json')
    receipt = json.loads(receipt_path.read_text()); receipt['recordSha256'] = owner._digest(record)
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(MigrationIOError, match='affairs_conflict_baseline_cycle'):
        owner._verified_baseline(root, 'snapshot-70', scope, target)


def test_successive_syncs_use_confirmed_previous_snapshots_as_baselines(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_affairs_conflicts import prepare_affairs_conflicts, list_affairs_conflicts, discover_affairs_baseline
        from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import personal_affairs_service
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        identity = native.bootstrap(root)['assistant']
        assert native.shutdown()['closed']
        scope = {'projectId': 'project', 'instanceId': 'instance', 'agentId': 'old-pa'}
        def row(title):
            return {'schemaVersion': 1, 'itemId': 'one', 'kind': 'todo', 'title': title,
                    'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        def archive(mid, title):
            rows = [row(title)]
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            base = root / 'history_sources/migrations' / mid
            source = base / 'sources/mps-ref/affairs/items.jsonl'
            source.parent.mkdir(parents=True)
            source.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            (base / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'migrationId': mid,
                'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
                    'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                    'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
            (base / '.confirmed').mkdir()
            return digest
        initial_hash = archive('initial', 'v0')
        archive('snapshot-1', 'v1'); archive('snapshot-2', 'v2'); archive('snapshot-3', 'v3')
        receipts = root / 'affairs_migrations'; receipts.mkdir()
        (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
            'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
            'sourceSha256': initial_hash, 'targetAgentId': identity['agentId'], 'itemCount': 1, 'published': True}))
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [row('v0')])
            for old, new, sync in [('initial', 'snapshot-1', 'sync-1'),
                                   ('snapshot-1', 'snapshot-2', 'sync-2'),
                                   ('snapshot-2', 'snapshot-3', 'sync-3')]:
                prepare_affairs_conflicts(lease, baseline_migration_id=old, snapshot_migration_id=new,
                    sync_id=sync, source_scope=scope)
                assert prepare_affairs_conflicts(lease, baseline_migration_id=old, snapshot_migration_id=new,
                    sync_id=sync, source_scope=scope)['reused']
                try: prepare_affairs_conflicts(lease, baseline_migration_id=old, snapshot_migration_id=new,
                                              sync_id=sync + '-competing', source_scope=scope)
                except MigrationIOError as error: assert str(error) == 'affairs_baseline_pending'
                else: raise AssertionError('second pending successor accepted')
                try: discover_affairs_baseline(root, source_scope=scope, target_agent_id=lease.agent_id)
                except MigrationIOError as error: assert str(error) == 'affairs_baseline_pending'
                else: raise AssertionError('prepared sync without receipt was accepted')
                result = reconcile_affairs(lease, sync_id=sync, source_scope=scope)
                assert result['appliedCount'] == 1 and result['conflictCount'] == 0
                assert discover_affairs_baseline(root, source_scope=scope, target_agent_id=lease.agent_id)['baselineMigrationId'] == new
                try: prepare_affairs_conflicts(lease, baseline_migration_id=old, snapshot_migration_id=new,
                                              sync_id=sync + '-stale', source_scope=scope)
                except MigrationIOError as error: assert str(error) == 'affairs_conflict_baseline_stale'
                else: raise AssertionError('stale baseline accepted after successful sync')
                listing = list_affairs_conflicts(root, sync_id=sync, source_scope=scope, target_agent_id=lease.agent_id)
                assert listing['unresolvedCount'] == 0 and listing['conflicts'][0]['syncStatus'] == 'applied'
            assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl') == [row('v3')]
            # Corrupt a previously published link; no later baseline may use it.
            path = root / 'affairs_sync_receipts' / (hashlib.sha256(b'sync-2').hexdigest() + '.json')
            saved = path.read_bytes(); receipt = json.loads(saved)
            for key, value in [('published', False), ('conflictCount', 1), ('recordSha256', '0' * 64)]:
                path.write_text(json.dumps({**receipt, key: value}))
                try: prepare_affairs_conflicts(lease, baseline_migration_id='snapshot-2', snapshot_migration_id='snapshot-3',
                                               sync_id='blocked-' + key, source_scope=scope)
                except MigrationIOError: pass
                else: raise AssertionError('unverified link accepted: ' + key)
            path.write_bytes(saved)
            # A later attempt to create a competing successor must be refused.
            archive('branch-snapshot', 'v1-branch')
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [row('v1')])
            try: prepare_affairs_conflicts(lease, baseline_migration_id='snapshot-1', snapshot_migration_id='branch-snapshot',
                                           sync_id='branch-sync', source_scope=scope)
            except MigrationIOError as error: assert str(error) == 'affairs_conflict_baseline_stale'
            else: raise AssertionError('stale competing successor accepted')
            assert discover_affairs_baseline(root, source_scope=scope, target_agent_id=lease.agent_id)['baselineMigrationId'] == 'snapshot-3'
    ''', config_text=TEST_MODEL_CONFIG)


def test_published_sync_classifies_changes_and_pending_never_claims_resolution(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_affairs_conflicts import (
            prepare_affairs_conflicts, discover_affairs_conflicts, list_affairs_conflicts, read_affairs_conflict)
        from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import personal_affairs_service
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        identity = native.bootstrap(root)['assistant']; assert native.shutdown()['closed']
        scope = {'projectId': 'project', 'instanceId': 'instance', 'agentId': 'old-pa'}
        def row(item, title):
            return {'schemaVersion': 1, 'itemId': item, 'kind': 'todo', 'title': title,
                    'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        old = [row('applied', 'old'), row('already', 'old'), row('diverged', 'old'), row('removed', 'old')]
        new = [row('applied', 'new'), row('already', 'new'), row('diverged', 'new')]
        def archive(mid, rows):
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            base = root / 'history_sources/migrations' / mid
            path = base / 'sources/mps-ref/affairs/items.jsonl'; path.parent.mkdir(parents=True); path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            (base / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'migrationId': mid,
                'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
                    'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                    'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
            (base / '.confirmed').mkdir(); return digest
        digest = archive('initial', old); archive('latest', new); archive('future', new)
        receipts = root / 'affairs_migrations'; receipts.mkdir()
        (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
            'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
            'sourceSha256': digest, 'targetAgentId': identity['agentId'], 'itemCount': len(old), 'published': True}))
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [
                old[0], new[1], row('diverged', 'user edit'), old[3]])
            prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                                      sync_id='sync', source_scope=scope)
            kwargs = dict(sync_id='sync', source_scope=scope, target_agent_id=lease.agent_id)
            before = list_affairs_conflicts(root, **kwargs)
            assert before['total'] == 4 and 'unresolvedCount' not in before
            result = reconcile_affairs(lease, sync_id='sync', source_scope=scope)
            assert result['appliedCount'] == 1 and result['conflictCount'] == 2
            listing = list_affairs_conflicts(root, **kwargs)
            assert listing['syncStatus'] == 'published' and listing['unresolvedCount'] == 2
            assert sorted(item['syncStatus'] for item in listing['conflicts']) == ['already', 'applied', 'unresolved', 'unresolved']
            detail = read_affairs_conflict(root, **kwargs, conflict_id=listing['conflicts'][0]['conflictId'])
            assert detail['syncStatus'] == listing['conflicts'][0]['syncStatus']
            found = discover_affairs_conflicts(root, target_agent_id=lease.agent_id)['sets'][0]
            assert found['conflictCount'] == 2 and found['differenceCount'] == 4
            # A published sync with unresolved changes is not a safe baseline.
            try: prepare_affairs_conflicts(lease, baseline_migration_id='latest', snapshot_migration_id='future',
                                          sync_id='blocked', source_scope=scope)
            except MigrationIOError: pass
            else: raise AssertionError('unresolved sync used as baseline')
            path = root / 'affairs_sync_receipts' / (hashlib.sha256(b'sync').hexdigest() + '.json')
            saved = path.read_bytes(); receipt = json.loads(saved)
            path.write_text(json.dumps({**receipt, 'published': False}))
            pending = list_affairs_conflicts(root, **kwargs)
            assert pending['syncStatus'] == 'pending' and pending['unresolvedCount'] is None
            assert {row['syncStatus'] for row in pending['conflicts']} == {'unknown'}
            assert discover_affairs_conflicts(root, target_agent_id=lease.agent_id)['sets'][0]['conflictCount'] is None
            path.write_text(json.dumps({**receipt, 'recordSha256': '0' * 64}))
            try: list_affairs_conflicts(root, **kwargs)
            except MigrationIOError as error: assert str(error) == 'affairs_sync_receipt_invalid'
            else: raise AssertionError('unbound receipt accepted for listing')
            path.write_bytes(saved)
    ''', config_text=TEST_MODEL_CONFIG)


def test_conflicts_are_isolated_searchable_and_preserve_target_at_capture(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_affairs_conflicts import (
            prepare_affairs_conflicts, discover_affairs_conflicts, resolve_affairs_conflict_scope,
            list_affairs_conflicts, read_affairs_conflict)
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import personal_affairs_service
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        identity = native.bootstrap(root)['assistant']
        native.shutdown()
        scope = {'projectId': 'project', 'instanceId': 'instance', 'agentId': 'old-pa'}
        def row(item_id, title):
            return {'schemaVersion': 1, 'itemId': item_id, 'kind': 'todo', 'title': title,
                    'note': 'private', 'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        old = [row('changed', 'old'), row('removed', 'deleted source'), row('same', 'unchanged')]
        new = [row('changed', 'new'), row('added', 'new source'), row('same', 'unchanged')]
        def archive(mid, rows):
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            digest = hashlib.sha256(raw).hexdigest()
            base = root / 'history_sources/migrations' / mid
            source = base / 'sources/mps-ref/affairs/items.jsonl'
            source.parent.mkdir(parents=True)
            source.write_bytes(raw)
            manifest = {'schemaVersion': 1, 'migrationId': mid, 'sourceScope': scope,
                'readOnly': True, 'untrustedContent': True, 'entries': [
                    {'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                     'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}
            (base / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
            (base / '.confirmed').mkdir()
            return digest, source
        old_hash, _ = archive('initial', old)
        _, latest_path = archive('latest', new)
        receipts = root / 'affairs_migrations'
        receipts.mkdir()
        receipt = {'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
            'sourceSha256': old_hash, 'targetAgentId': identity['agentId'],
            'itemCount': len(old), 'published': True}
        (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps(receipt))
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            existing = [row('changed', 'target changed by user'), row('added', 'target unrelated')]
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', existing)
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            original_bytes = ledger.read_bytes()
            args = dict(baseline_migration_id='initial', snapshot_migration_id='latest',
                        sync_id='final', source_scope=scope)
            # A crash after the atomic conflict publication reuses the same
            # immutable request rather than taking a second target snapshot.
            from core.assistant_runtime import migration_affairs_conflicts as owner
            atomic = owner.atomic_write_json
            def crash_after_publish(*a, **k):
                atomic(*a, **k)
                raise RuntimeError('synthetic interruption')
            owner.atomic_write_json = crash_after_publish
            try:
                try: prepare_affairs_conflicts(lease, **args)
                except RuntimeError: pass
                else: raise AssertionError('interruption not injected')
            finally:
                owner.atomic_write_json = atomic
            outcome = prepare_affairs_conflicts(lease, **args)
            assert outcome['conflictCount'] == 3 and outcome['reused']
            assert not outcome['sourceQuiesced'] and not outcome['readyForCutover']
            assert ledger.read_bytes() == original_bytes
            read_args = dict(sync_id='final', source_scope=scope, target_agent_id=lease.agent_id)
            discovered = discover_affairs_conflicts(root, target_agent_id=lease.agent_id)
            assert discovered['sets'] == [{'syncId': 'final', 'sourceScope': scope, 'conflictCount': 3}]
            assert resolve_affairs_conflict_scope(root, sync_id='final', target_agent_id=lease.agent_id) == scope
            page = list_affairs_conflicts(root, **read_args, limit=2)
            assert page['total'] == 3 and page['nextOffset'] == 2
            assert page['sourceSnapshotOnly'] and page['targetSnapshotOnly']
            assert len(list_affairs_conflicts(root, **read_args, offset=2)['conflicts']) == 1
            found = list_affairs_conflicts(root, **read_args, query='NEW SOURCE')['conflicts']
            assert len(found) == 1 and found[0]['kind'] == 'added'
            detail = read_affairs_conflict(root, **read_args, conflict_id=found[0]['conflictId'])
            payload = json.loads(detail['text'])
            assert payload['source']['title'] == 'new source'
            assert payload['target']['title'] == 'target unrelated'
            assert detail['targetSnapshotOnly'] and detail['sourceSnapshotOnly']
            fragments, cursor = [], 0
            while cursor is not None:
                part = read_affairs_conflict(root, **read_args, conflict_id=found[0]['conflictId'],
                                             character_offset=cursor, max_characters=17)
                assert len(part['text']) <= 17
                fragments.append(part['text'])
                cursor = part['nextCharacterOffset']
            assert json.loads(''.join(fragments)) == payload
            removed = list_affairs_conflicts(root, **read_args, query='deleted source')['conflicts'][0]
            assert removed['kind'] == 'removed' and removed['targetState'] == 'missing'
            detail = read_affairs_conflict(root, **read_args, conflict_id=removed['conflictId'])
            payload = json.loads(detail['text'])
            assert payload['baseline']['title'] == 'deleted source' and payload['source'] is None
            assert payload['target'] is None
            # Later user changes are not undone, and the captured target remains reviewable.
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [row('changed', 'later user edit')])
            later = ledger.read_bytes()
            assert prepare_affairs_conflicts(lease, **args)['reused']
            assert ledger.read_bytes() == later
            captured = read_affairs_conflict(root, **read_args, conflict_id=found[0]['conflictId'])
            assert json.loads(captured['text'])['target']['title'] == 'target unrelated'
            # A historical second pending record cannot be hidden by retrying
            # this same sync_id; the retry still checks the rest of the graph.
            record = json.loads(owner._record_path(root, 'final').read_text())
            record['syncId'] = 'other-pending'
            for conflict in record['conflicts']:
                conflict['conflictId'] = owner._digest({'syncId': 'other-pending', 'sourceScope': scope,
                    'itemId': conflict['itemId'], 'kind': conflict['kind']})
            extra = owner._record_path(root, 'other-pending'); extra.write_text(json.dumps(record))
            try: prepare_affairs_conflicts(lease, **args)
            except MigrationIOError as error: assert str(error) == 'affairs_baseline_pending'
            else: raise AssertionError('retry ignored another pending request')
            extra.unlink()
            # A second request cannot be created while the first is pending.
            try: prepare_affairs_conflicts(lease, **{**args, 'sync_id': 'interrupted'})
            except MigrationIOError as error: assert str(error) == 'affairs_baseline_pending'
            else: raise AssertionError('parallel pending successor accepted')
            assert ledger.read_bytes() == later
            for wrong in ({**read_args, 'source_scope': {**scope, 'agentId': 'other'}},
                          {**read_args, 'target_agent_id': 'other'}):
                try: list_affairs_conflicts(root, **wrong)
                except MigrationIOError: pass
                else: raise AssertionError('cross-scope read accepted')
            marker = latest_path.parents[2].parent / '.confirmed'
            marker.rmdir()
            try: list_affairs_conflicts(root, **read_args)
            except MigrationIOError as error: assert str(error) == 'affairs_conflict_archive_unconfirmed'
            else: raise AssertionError('unconfirmed archive accepted')
            marker.mkdir()
            latest_path.write_bytes(b'tampered')
            try: prepare_affairs_conflicts(lease, **args)
            except MigrationIOError as error: assert str(error) == 'affairs_conflict_archive_invalid'
            else: raise AssertionError('tampered archive accepted')
            assert ledger.read_bytes() == later
    ''', config_text=TEST_MODEL_CONFIG)
