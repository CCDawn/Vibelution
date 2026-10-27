"""Convergence receipts never modify live affairs and require a fresh match."""
from textwrap import dedent
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_SETUP = r'''
    import hashlib, json, os
    from contextlib import contextmanager
    from pathlib import Path
    from core.assistant_runtime import native, migration_affairs_convergence as convergence
    from core.assistant_runtime.migration_affairs_conflicts import prepare_affairs_conflicts
    from core.assistant_runtime.migration_affairs_sync import reconcile_affairs
    from core.assistant_runtime.migration_io import MigrationIOError
    from core.assistant_runtime.online_affairs_sync_lease import OnlineAffairsSyncOwner
    from core.web.services import personal_affairs_service
    root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
    assistant = native.bootstrap(root)['assistant']
    scope = {'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'}
    row = {'schemaVersion': 1, 'itemId': 'item', 'kind': 'todo', 'title': 'old',
           'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
    desired = {**row, 'title': 'source'}
    def archive(mid, rows):
        raw = b''.join(json.dumps(item).encode() + b'\n' for item in rows)
        base = root / 'history_sources/migrations' / mid
        file = base / 'sources/mps-ref/affairs/items.jsonl'
        file.parent.mkdir(parents=True)
        file.write_bytes(raw)
        (base / 'manifest.json').write_text(json.dumps({
            'schemaVersion': 2, 'migrationId': mid, 'sourceScope': scope, 'readOnly': True,
            'untrustedContent': True, 'entries': [{'sourceRef': 'mps-ref', 'category': 'personal_affairs',
                'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}]}))
        (base / '.confirmed').mkdir()
        return hashlib.sha256(raw).hexdigest()
    old_hash = archive('initial', [row])
    archive('latest', [desired])
    receipts = root / 'affairs_migrations'
    receipts.mkdir()
    (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
        'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
        'sourceSha256': old_hash, 'targetAgentId': assistant['agentId'], 'itemCount': 1, 'published': True}))
    @contextmanager
    def guard(generation, turn): yield
    owner = OnlineAffairsSyncOwner('generation', guard)
    args = dict(generation='generation', turn_id='turn', baseline_migration_id='initial', source_scope=scope)
'''


def _fixture(tmp_path, code):
    _run(tmp_path, dedent(_SETUP) + dedent(code), config_text=TEST_MODEL_CONFIG)


def test_convergence_requires_current_match_and_never_writes_ledger(tmp_path):
    _fixture(tmp_path, r'''
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                assert reconcile_affairs(lease, sync_id='sync', source_scope=scope)['conflictCount'] == 1
                ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
                before = ledger.read_bytes()
                try: convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                except MigrationIOError as e: assert str(e) == 'affairs_convergence_not_reached'
                else: raise AssertionError('nonmatching target converged')
                assert ledger.read_bytes() == before
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                before = ledger.read_bytes()
                result = convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                assert result['convergedCount'] == 1 and not result['reused']
                assert not result['sourceQuiesced'] and not result['readyForCutover']
                assert ledger.read_bytes() == before
                assert convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
                assert convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)['reused']
                from core.assistant_runtime import migration_affairs_conflicts as conflicts
                try: conflicts.discover_affairs_baseline(root, source_scope=scope, target_agent_id=lease.agent_id)
                except MigrationIOError as e: assert str(e) == 'affairs_baseline_unresolved'
                else: raise AssertionError('unlocked discovery accepted convergence')
                with conflicts.locked_affairs_target(root, target_agent_id=lease.agent_id) as token:
                    found = conflicts.discover_affairs_baseline_locked(root, source_scope=scope,
                        target_agent_id=lease.agent_id, target=token)
                    assert found['baselineMigrationId'] == 'latest'
                    assert conflicts.verified_affairs_baseline_locked(root, 'latest', scope, lease.agent_id,
                        target=token)[0] == [desired]
                    import threading
                    rejected = []
                    def other_thread():
                        try: conflicts.verified_affairs_baseline_locked(root, 'latest', scope, lease.agent_id, target=token)
                        except MigrationIOError: rejected.append(True)
                    worker = threading.Thread(target=other_thread)
                    worker.start(); worker.join(timeout=5)
                    assert not worker.is_alive() and rejected == [True]
                try: conflicts.verified_affairs_baseline_locked(root, 'latest', scope, lease.agent_id, target=token)
                except MigrationIOError as e: assert str(e) == 'affairs_target_lock_required'
                else: raise AssertionError('expired target token accepted')
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [row])
                assert not convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[row])
                with conflicts.locked_affairs_target(root, target_agent_id=lease.agent_id) as token:
                    assert conflicts.discover_affairs_baseline_locked(root, source_scope=scope,
                        target_agent_id=lease.agent_id, target=token)['baselineMigrationId'] == 'latest'
        finally:
            assert native.shutdown()['closed']
    ''')


def test_interrupted_confirmation_stays_invisible_and_verified_retry_resumes(tmp_path):
    _fixture(tmp_path, r'''
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                original = convergence._confirm_archive
                def interrupt(*args, **kwargs): raise RuntimeError('injected')
                convergence._confirm_archive = interrupt
                try:
                    try: convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                    except RuntimeError: pass
                    else: raise AssertionError('no interruption')
                finally: convergence._confirm_archive = original
                assert not convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
                assert convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)['reused']
                assert convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
        finally:
            assert native.shutdown()['closed']
    ''')


def test_interrupted_proof_write_retries_and_pins_source_during_confirmation(tmp_path):
    _fixture(tmp_path, r'''
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                original_temp = convergence._write_temp_file
                def interrupt(path, *args, **kwargs):
                    (path.parent / '.proof.json.interrupted.tmp').write_bytes(b'partial')
                    raise RuntimeError('injected crash')
                convergence._write_temp_file = interrupt
                try:
                    try: convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                    except RuntimeError: pass
                    else: raise AssertionError('no interruption')
                finally: convergence._write_temp_file = original_temp
                original_confirm = convergence._confirm_archive
                attempts = []
                source = root / 'history_sources/migrations/latest/sources/mps-ref/affairs/items.jsonl'
                ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
                def probe(*args, **kwargs):
                    for path in (source, ledger):
                        try: path.write_bytes(b'tampered')
                        except OSError: attempts.append(True)
                        else: raise AssertionError('source or target file was not pinned')
                    return original_confirm(*args, **kwargs)
                convergence._confirm_archive = probe
                try: result = convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                finally: convergence._confirm_archive = original_confirm
                assert result['convergedCount'] == 1 and len(attempts) == 2
                assert convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
        finally:
            assert native.shutdown()['closed']
    ''')


def test_missing_source_and_unconfirmed_receipt_cannot_converge():
    from core.assistant_runtime.migration_affairs_convergence import _unresolved
    from core.assistant_runtime.migration_io import MigrationIOError
    import pytest
    record = {'conflicts': [{'conflictId': 'c', 'itemId': 'x', 'source': None}]}
    receipt = {'published': True, 'decisions': [{'conflictId': 'c', 'status': 'unresolved'}]}
    with pytest.raises(MigrationIOError, match='affairs_convergence_not_reached'):
        _unresolved(record, receipt, [])
    receipt['published'] = False
    with pytest.raises(MigrationIOError, match='affairs_convergence_receipt_unconfirmed'):
        _unresolved(record, receipt, [])


def test_convergence_rejects_untrusted_lease_before_reading_target(monkeypatch):
    from core.assistant_runtime import migration_affairs_convergence as convergence
    from core.assistant_runtime.migration_io import MigrationIOError
    import pytest
    monkeypatch.setattr(convergence, '_load', lambda *args: pytest.fail('read before capability check'))
    with pytest.raises(MigrationIOError, match='affairs_profile_lease_required'):
        convergence.converge_affairs(object(), sync_id='sync', source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'a'})
def test_revocation_before_confirmation_is_recoverable_and_proof_tamper_is_rejected(tmp_path):
    _fixture(tmp_path, r'''
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                original = convergence._confirm_archive
                def revoke_then_confirm(*values, **kwargs):
                    assert owner.revoke() is False
                    return original(*values, **kwargs)
                convergence._confirm_archive = revoke_then_confirm
                try:
                    try: convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                    except MigrationIOError as e: assert str(e) == 'affairs_profile_lease_required'
                    else: raise AssertionError('revoked lease confirmed')
                finally: convergence._confirm_archive = original
                assert not convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
            owner2 = OnlineAffairsSyncOwner('generation', guard)
            with owner2.admit(**args) as lease:
                assert convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)['reused']
                directory = convergence._proof_directory(root, 'sync')
                path = directory / 'proof.json'
                proof = json.loads(path.read_text(encoding='utf-8'))
                proof['sourceQuiesced'] = 0
                path.write_text(json.dumps(proof), encoding='utf-8')
                try: convergence.verify_affairs_convergence(root, sync_id='sync', source_scope=scope,
                    target_agent_id=lease.agent_id, target_rows=[desired])
                except MigrationIOError as e: assert str(e) == 'affairs_convergence_invalid'
                else: raise AssertionError('malformed proof accepted')
        finally:
            assert native.shutdown()['closed']
    ''')


def test_online_prepare_and_convergence_do_not_wait_for_busy_ledger(tmp_path):
    _fixture(tmp_path, r'''
        import threading, time
        from core.infrastructure.file_lock import cross_process_file_lock
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
                acquired, release = threading.Event(), threading.Event()
                def holder():
                    with cross_process_file_lock(ledger):
                        acquired.set(); assert release.wait(timeout=5)
                worker = threading.Thread(target=holder); worker.start(); assert acquired.wait(timeout=5)
                try:
                    start = time.monotonic()
                    try: prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                        sync_id='sync', source_scope=scope)
                    except TimeoutError: pass
                    else: raise AssertionError('busy ledger admitted prepare')
                    assert time.monotonic() - start < 2
                finally:
                    release.set(); worker.join(timeout=5)
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                acquired, release = threading.Event(), threading.Event()
                worker = threading.Thread(target=holder); worker.start(); assert acquired.wait(timeout=5)
                try:
                    start = time.monotonic()
                    try: convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                    except TimeoutError: pass
                    else: raise AssertionError('busy ledger admitted convergence')
                    assert time.monotonic() - start < 2
                finally:
                    release.set(); worker.join(timeout=5)
        finally:
            assert native.shutdown()['closed']
    ''')


def test_prepare_accepts_converged_head_with_native_admission_and_rechecks_target(tmp_path):
    _fixture(tmp_path, r'''
        from core.assistant_runtime import migration_affairs_conflicts as conflicts
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
            after = {**row, 'title': 'next source'}
            archive('later', [after])
            owner2 = OnlineAffairsSyncOwner('generation', guard)
            with owner2.admit(generation='generation', turn_id='turn', baseline_migration_id='latest', source_scope=scope) as lease:
                proof_path = convergence._proof_directory(root, 'sync') / 'proof.json'
                original_write = conflicts.atomic_write_json
                attempts = []
                def probe(*values, **kwargs):
                    try: proof_path.write_bytes(b'tampered')
                    except OSError: attempts.append(True)
                    else: raise AssertionError('proof not pinned during prepare')
                    return original_write(*values, **kwargs)
                conflicts.atomic_write_json = probe
                try:
                    result = prepare_affairs_conflicts(lease, baseline_migration_id='latest', snapshot_migration_id='later',
                        sync_id='next', source_scope=scope)
                finally: conflicts.atomic_write_json = original_write
                assert result['conflictCount'] == 1 and not result['reused']
                assert attempts
                result = reconcile_affairs(lease, sync_id='next', source_scope=scope)
                assert result['appliedCount'] == 1 and result['conflictCount'] == 0
                from core.assistant_runtime.affairs_conflict_actions import _sync_receipt_status
                assert _sync_receipt_status(root, 'next', lease.agent_id)['state'] == 'published'
                from core.assistant_runtime.affairs_conflict_actions import execute as read_action
                runtime = {'agentId': lease.agent_id, 'sessionId': lease.session_id}
                sets = read_action('affairs_conflict_sets', {}, runtime)
                assert any(item['syncId'] == 'next' for item in sets['sets'])
                page = read_action('affairs_conflict_list', {'sync_id': 'next'}, runtime)
                assert page['total'] == 1 and page['conflicts'][0]['syncStatus'] == 'planned_apply'
                detail = read_action('affairs_conflict_read', {'sync_id': 'next',
                    'conflict_id': page['conflicts'][0]['conflictId']}, runtime)
                assert detail['syncStatus'] == 'planned_apply'
        finally:
            assert native.shutdown()['closed']
    ''')


def test_locked_verification_is_reentrant_and_releases_ledger_before_atomic_write(tmp_path):
    _fixture(tmp_path, r'''
        from core.assistant_runtime import migration_affairs_conflicts as conflicts, migration_affairs_sync as sync
        from core.assistant_runtime.migration_io import migration_target_lock, pinned_mutable_file, pinned_target_directory
        from core.infrastructure.file_lock import cross_process_file_lock
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id='sync', source_scope=scope)
                reconcile_affairs(lease, sync_id='sync', source_scope=scope)
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [desired])
                convergence.converge_affairs(lease, sync_id='sync', source_scope=scope)
                ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
                receipts = root / 'affairs_sync_receipts'
                with pinned_target_directory(receipts), migration_target_lock(receipts), \
                        pinned_mutable_file(ledger.with_name(ledger.name + '.lock')), cross_process_file_lock(ledger):
                    with conflicts.locked_affairs_target(root, target_agent_id=lease.agent_id) as token:
                        result = conflicts.discover_affairs_baseline_locked(root, source_scope=scope,
                            target_agent_id=lease.agent_id, target=token)
                        assert result['baselineMigrationId'] == 'latest'
                    # Keep the outer mutex and ledger lock, but the helper's
                    # read-only file handles are closed before replacement.
                    after = {**desired, 'title': 'legitimate new value'}
                    encoded = (json.dumps(after, ensure_ascii=False, sort_keys=True) + '\n').encode()
                    sync._replace_ledger(ledger, encoded)
                    assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl') == [after]
        finally:
            assert native.shutdown()['closed']
    ''')
