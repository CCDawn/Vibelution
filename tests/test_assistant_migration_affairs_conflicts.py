"""Synthetic source archives and native target, no production data."""
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


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
            outcome = prepare_affairs_conflicts(lease, **args)
            assert outcome['conflictCount'] == 3 and not outcome['reused']
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
            # An interruption after the single atomic publication is recovered
            # by reusing the saved snapshot, never by touching the live ledger.
            from core.assistant_runtime import migration_affairs_conflicts as owner
            atomic = owner.atomic_write_json
            def crash_after_publish(*a, **k):
                atomic(*a, **k)
                raise RuntimeError('synthetic interruption')
            owner.atomic_write_json = crash_after_publish
            retry_args = {**args, 'sync_id': 'interrupted'}
            try:
                try: prepare_affairs_conflicts(lease, **retry_args)
                except RuntimeError: pass
                else: raise AssertionError('interruption not injected')
            finally:
                owner.atomic_write_json = atomic
            assert prepare_affairs_conflicts(lease, **retry_args)['reused']
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
