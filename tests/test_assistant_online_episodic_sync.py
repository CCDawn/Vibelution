"""Native-ledger sync under a synthetic trusted host and isolated profile."""
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_SETUP = r'''
import hashlib, json, os
from contextlib import contextmanager
from pathlib import Path
from core.assistant_runtime import native
from core.assistant_runtime.initial_migration_binding import _intent_anchor, source_identity, target_identity
from core.assistant_runtime.main_control import initial_migration_id
from core.assistant_runtime.online_episodic_sync import OnlineEpisodicSyncOwner, reconcile_episodic
from core.assistant_runtime.migration_io import MigrationIOError
from core.web.services.agent_directory import episodic_memory as episodes
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
assistant = native.bootstrap(root)['assistant']
project, workspace = root.parent / 'legacy-project', root.parent / 'legacy-workspace'
project.mkdir(); workspace.mkdir()
scope = {'projectId': 'source-project', 'instanceId': 'source-instance', 'agentId': 'old-pa'}
initial = initial_migration_id('registered:1', '', 'personal')
sd, pd, wd = source_identity(scope, project, workspace)
td, target_directory = target_identity(root, assistant['agentId'], assistant['directSessionId'])
intent = {'schemaVersion': 1, 'registeredProjectId': 'registered:1', 'sourceScope': scope,
          'category': 'personal', 'turnId': 'initial-turn', 'operationId': initial, 'revision': 1,
          'sourceIdentityDigest': sd, 'registryDigest': 'a' * 64, 'targetIdentityDigest': td,
          'projectDirectory': pd, 'workspaceDirectory': wd, 'targetDirectory': target_directory,
          'targetAgentId': assistant['agentId'], 'targetSessionId': assistant['directSessionId'],
          'authority': 'native_policy_admitted', 'readyForCutover': False}
intent_path = root / 'initial_migration_intents' / _intent_anchor(intent) / 'intent.json'
intent_path.parent.mkdir(parents=True); intent_path.write_text(json.dumps(intent))
claim = root / 'initial_migration_claims' / initial / 'claim.json'
claim.parent.mkdir(parents=True); claim.write_text(json.dumps({'schemaVersion': 1, 'operationId': initial, 'category': 'personal'}))
old = {'schemaVersion': 1, 'episodeId': 'one', 'eventId': 'one', 'agentId': 'old-pa',
       'occurredAt': '2025-02-01T00:00:00Z', 'kind': 'note', 'text': 'old', 'refs': [],
       'validFrom': '2025-02-01T00:00:00Z', 'validUntil': '', 'supersededByEpisodeId': ''}
affair = {'schemaVersion': 1, 'itemId': 'a', 'kind': 'todo', 'title': 'fixture',
          'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
def encoded(rows): return b''.join(json.dumps(row).encode() + b'\n' for row in rows)
def archive(mid, rows, with_affair=False):
    dest = root / 'history_sources' / 'migrations' / mid
    dest.mkdir(parents=True)
    entries = []
    for category, relative, body in [('episodic_memory', 'episodic_events.jsonl', encoded(rows))] + (
        [('personal_affairs', 'affairs/items.jsonl', encoded([affair]))] if with_affair else []):
        item = dest / 'sources/ref' / relative
        item.parent.mkdir(parents=True, exist_ok=True); item.write_bytes(body)
        entries.append({'sourceRef': 'ref', 'category': category, 'path': 'sources/ref/' + relative,
                        'sha256': hashlib.sha256(body).hexdigest(), 'size': len(body)})
    (dest / 'manifest.json').write_text(json.dumps({'schemaVersion': 2, 'migrationId': mid, 'sourceScope': scope,
        'readOnly': True, 'untrustedContent': True, 'activePluginStateImported': False, 'sourceComplete': False,
        'snapshotCompleteAtScan': False, 'entries': entries, 'readyForCutover': False}))
    (dest / '.confirmed').mkdir()
    return entries
entries = archive(initial, [old], True)
for directory, count_key, entry in [('episodic_migrations', 'episodeCount', entries[0]),
                                    ('affairs_migrations', 'itemCount', entries[1])]:
    dest = root / directory / (hashlib.sha256(initial.encode()).hexdigest() + '.json')
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps({'schemaVersion': 1, 'migrationId': initial, 'sourceScope': scope,
        'sourceSha256': entry['sha256'], 'targetAgentId': assistant['agentId'], count_key: 1, 'published': True}))
with episodes.episodic_transaction(assistant['agentId']) as tx:
    tx.events.append({**old, 'agentId': assistant['agentId']}); tx._dirty = True
@contextmanager
def guard(generation, turn):
    assert (generation, turn) == ('generation', 'turn')
    yield
owner = OnlineEpisodicSyncOwner('generation', guard)
args = dict(generation='generation', turn_id='turn', initial_operation_id=initial, source_scope=scope,
            project=project, workspace=workspace, verify=lambda: None)
'''


def test_real_transaction_chains_receipts_and_preserves_deleted_target(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    second = {**old, 'episodeId': 'two', 'eventId': 'two', 'text': 'new'}
    archive('sync-one', [old, second])
    with owner.admit(**args) as lease:
        result = reconcile_episodic(lease, sync_id='sync-one')
        assert result['appliedCount'] == 1 and result['conflictCount'] == 0
        assert reconcile_episodic(lease, sync_id='sync-one')['reused']
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[:] = [row for row in tx.events if row['episodeId'] != 'two']; tx._dirty = True
    archive('sync-two', [old, {**second, 'text': 'source edit'}])
    with owner.admit(**args) as lease:
        result = reconcile_episodic(lease, sync_id='sync-two')
        assert result['appliedCount'] == 0 and result['conflictCount'] == 1
    assert [row['episodeId'] for row in episodes.list_episodic_events(assistant['agentId'], include_superseded=True)] == ['one']
    archive('sync-three', [old, second])
    with owner.admit(**args) as lease:
        refreshed = reconcile_episodic(lease, sync_id='sync-three')
        assert refreshed['conflictCount'] > 0 and refreshed['appliedCount'] == 0
    assert [row['episodeId'] for row in episodes.list_episodic_events(assistant['agentId'], include_superseded=True)] == ['one']
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_pending_receipt_recovers_only_matching_published_target(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime import online_episodic_sync as sync
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    archive('sync-one', [old, second])
    original = sync._write_receipt
    def crash(path, receipt):
        if receipt['published']: raise RuntimeError('synthetic crash')
        original(path, receipt)
    sync._write_receipt = crash
    try:
        with owner.admit(**args) as lease:
            try: reconcile_episodic(lease, sync_id='sync-one')
            except RuntimeError: pass
            else: raise AssertionError('crash not injected')
    finally:
        sync._write_receipt = original
    with owner.admit(**args) as lease:
        result = reconcile_episodic(lease, sync_id='sync-one', confirmation_only=True)
        assert result['reused'] and result['appliedCount'] == 1
    assert len(episodes.list_episodic_events(assistant['agentId'], include_superseded=True)) == 2
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_pending_receipt_cannot_replay_after_user_edit(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime import online_episodic_sync as sync
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    archive('sync-one', [old, second])
    original = sync._write_receipt
    def crash(path, receipt):
        if receipt['published']: raise RuntimeError('synthetic crash')
        original(path, receipt)
    sync._write_receipt = crash
    try:
        with owner.admit(**args) as lease:
            try: reconcile_episodic(lease, sync_id='sync-one')
            except RuntimeError: pass
            else: raise AssertionError('crash not injected')
    finally:
        sync._write_receipt = original
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[:] = [row for row in tx.events if row['episodeId'] != 'two']; tx._dirty = True
    with owner.admit(**args) as lease:
        try: reconcile_episodic(lease, sync_id='sync-one', confirmation_only=True)
        except MigrationIOError as error: assert str(error) == 'episodic_sync_outcome_unknown'
        else: raise AssertionError('changed target was treated as the original commit')
    assert [r['episodeId'] for r in episodes.list_episodic_events(assistant['agentId'], include_superseded=True)] == ['one']
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_source_identity_and_first_import_receipt_are_required(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    with owner.admit(**args) as lease:
        assert lease.agent_id == assistant['agentId']
    copied = root.parent / 'another-project'
    copied.mkdir()
    try:
        with owner.admit(**{**args, 'project': copied}): pass
    except MigrationIOError as error: assert str(error) == 'episodic_sync_identity_changed'
    else: raise AssertionError('a different physical source was admitted')
    receipt = root / 'episodic_migrations' / (hashlib.sha256(initial.encode()).hexdigest() + '.json')
    receipt.unlink()
    try:
        with owner.admit(**args): pass
    except (MigrationIOError, OSError): pass
    else: raise AssertionError('first import without its receipt was admitted')
    from types import SimpleNamespace
    from core.assistant_runtime.online_episodic_sync import synchronize_episodic, EpisodicSyncPrewrite
    paths = SimpleNamespace(project_root=project, project_id=scope['projectId'], instance_id=scope['instanceId'])
    binding = (project, workspace, paths, 'old-pa', lambda: None, ())
    try:
        synchronize_episodic(preview_binding=binding, owner=owner, generation='generation', turn_id='turn',
            initial_operation_id=initial, sync_id='episodic-' + 'a' * 40)
    except EpisodicSyncPrewrite as error: assert str(error) == 'baseline_unavailable'
    else: raise AssertionError('missing initial receipt did not reject before writing')
    try: reconcile_episodic(object(), sync_id='sync-one')
    except MigrationIOError: pass
    else: raise AssertionError('forged lease admitted')
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_tampered_archive_and_cross_thread_lease_fail_closed(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    import threading
    archive('sync-one', [old])
    with owner.admit(**args) as lease:
        failures = []
        def other_thread():
            try: reconcile_episodic(lease, sync_id='sync-one')
            except MigrationIOError: failures.append(True)
        worker = threading.Thread(target=other_thread); worker.start(); worker.join(5)
        assert not worker.is_alive() and failures == [True]
        source = root / 'history_sources/migrations/sync-one/sources/ref/episodic_events.jsonl'
        source.write_bytes(encoded([{**old, 'text': 'tampered'}]))
        try: reconcile_episodic(lease, sync_id='sync-one')
        except MigrationIOError as error: assert str(error) == 'episodic_sync_archive_invalid'
        else: raise AssertionError('modified archive accepted')
        assert owner.revoke() is False
        try: reconcile_episodic(lease, sync_id='sync-one')
        except MigrationIOError: pass
        else: raise AssertionError('revoked lease accepted')
    assert owner.drained()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_coordinator_captures_source_and_commits_under_live_owner(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from types import SimpleNamespace
    from core.assistant_runtime.migration_io import read_stable_file, verify_snapshot
    from core.assistant_runtime.online_episodic_sync import synchronize_episodic
    registry = workspace / 'agents/agents.json'
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'agents': [{'agentId': 'old-pa', 'directSessionId': 'direct',
        'roleKey': 'personal_assistant', 'status': 'active',
        'metadata': {'personalAssistantProfile': 'personal_assistant_v1'}}]}))
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    source = workspace / 'agents/old-pa/events/episodic_events.jsonl'
    source.parent.mkdir(parents=True); source.write_bytes(encoded([old, second]))
    authority = read_stable_file(registry, 16 * 1024 * 1024)
    paths = SimpleNamespace(project_root=project, project_id=scope['projectId'], instance_id=scope['instanceId'])
    binding = (project, workspace, paths, 'old-pa', lambda: verify_snapshot(authority), (authority,))
    result = synchronize_episodic(preview_binding=binding, owner=owner, generation='generation', turn_id='turn',
        initial_operation_id=initial, sync_id='episodic-' + 'b' * 40)
    assert result['appliedCount'] == 1 and result['conflictCount'] == 0
    assert {r['episodeId'] for r in episodes.list_episodic_events(assistant['agentId'], include_superseded=True)} == {'one', 'two'}
    assert source.read_bytes() == encoded([old, second])
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_original_receipt_recovery_validates_all_successors(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    third = {**old, 'episodeId': 'three', 'eventId': 'three'}
    archive('sync-one', [old, second]); archive('sync-two', [old, second, third])
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id='sync-one')['appliedCount'] == 1
        assert reconcile_episodic(lease, sync_id='sync-two')['appliedCount'] == 1
        try: reconcile_episodic(lease, sync_id='sync-one', confirmation_only=True)
        except MigrationIOError as error: assert str(error) == 'episodic_sync_outcome_unknown'
        else: raise AssertionError('changed target treated as original result')
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[:] = [r for r in tx.events if r['episodeId'] != 'three']; tx._dirty = True
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id='sync-one', confirmation_only=True)['reused']
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_conflict_limit_is_rejected_before_sync_receipt(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime import online_episodic_sync as sync
    archive('sync-one', [old])
    original = sync.plan_episodic_sync
    sync.plan_episodic_sync = lambda *args, **kwargs: {'rows': [], 'appliedCount': 0, 'conflictCount': 4097}
    try:
        with owner.admit(**args) as lease:
            try: reconcile_episodic(lease, sync_id='sync-one')
            except sync.EpisodicSyncPrewrite as error: assert str(error) == 'row_limit'
            else: raise AssertionError('oversized conflict receipt admitted')
    finally:
        sync.plan_episodic_sync = original
    receipt = root / 'episodic_sync_receipts' / (hashlib.sha256(b'sync-one').hexdigest() + '.json')
    assert not receipt.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_ledger_lock_busy_is_rejected_before_any_receipt(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime import online_episodic_sync as sync
    archive('sync-one', [old])
    original = sync.cross_process_file_lock
    @contextmanager
    def busy(*args, **kwargs):
        raise TimeoutError('busy')
        yield
    sync.cross_process_file_lock = busy
    try:
        with owner.admit(**args) as lease:
            try: reconcile_episodic(lease, sync_id='sync-one')
            except sync.EpisodicSyncPrewrite as error: assert str(error) == 'busy'
            else: raise AssertionError('busy target was not rejected')
    finally:
        sync.cross_process_file_lock = original
    receipt = root / 'episodic_sync_receipts' / (hashlib.sha256(b'sync-one').hexdigest() + '.json')
    assert not receipt.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_review_keep_target_and_prevent_source_reappearance_resurrection(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime.episodic_conflict_actions import execute
    conflict = 'episodic-' + '1' * 40
    resolution = 'episodic-' + '2' * 40
    future = 'episodic-' + '3' * 40
    archive(conflict, [])
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=conflict)['conflictCount'] == 1
    runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
    review = execute('episodic_conflict_review', {'sync_id': conflict}, runtime)
    assert review['total'] == 1 and review['differences'][0]['kind'] == 'removed'
    assert review['differences'][0]['target']['text'] == 'old' and review['sourceSnapshotOnly']
    assert 'path' not in json.dumps(review).lower()
    archive(resolution, [])
    # Any target edit after inspection invalidates the approval-bound review.
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[0]['text'] = 'user edited'; tx._dirty = True
    try: execute('episodic_conflict_review', {'sync_id': conflict, 'character_offset': 1, 'review_token': review['reviewToken']}, runtime)
    except ValueError: pass
    else: raise AssertionError('mixed pages from changed target were accepted')
    with owner.admit(**args) as lease:
        try: reconcile_episodic(lease, sync_id=resolution, resolve_sync_id=conflict, review_token=review['reviewToken'])
        except MigrationIOError as error: assert str(error) == 'review_changed'
        else: raise AssertionError('stale target review accepted')
    review = execute('episodic_conflict_review', {'sync_id': conflict}, runtime)
    page = execute('episodic_conflict_review', {'sync_id': conflict, 'character_offset': 1, 'review_token': review['reviewToken']}, runtime)
    assert page['reviewToken'] == review['reviewToken'] and page['differences'][0]['target']['text'] == 'ser edited'
    with owner.admit(**args) as lease:
        result = reconcile_episodic(lease, sync_id=resolution, resolve_sync_id=conflict, review_token=review['reviewToken'])
        assert result['appliedCount'] == result['conflictCount'] == 0
    assert episodes.list_episodic_events(assistant['agentId'], include_superseded=True)[0]['text'] == 'user edited'
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events.clear(); tx._dirty = True
    archive(future, [old])
    with owner.admit(**args) as lease:
        result = reconcile_episodic(lease, sync_id=future)
        assert result['conflictCount'] == 1 and result['appliedCount'] == 0
    assert episodes.list_episodic_events(assistant['agentId'], include_superseded=True) == []
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_review_exposes_non_text_conflicts_and_pages_metadata(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime.episodic_conflict_actions import execute
    conflict = 'episodic-' + '1' * 40
    changed = {**old, 'kind': 'preference', 'refs': [{'type': 'session', 'id': 's' * 300}]}
    archive(conflict, [changed])
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[0]['kind'] = 'session_fact'; tx._dirty = True
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=conflict)['conflictCount'] == 1
    runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
    review = execute('episodic_conflict_review', {'sync_id': conflict, 'max_characters': 80}, runtime)
    item = review['differences'][0]
    assert item['source']['text'] == item['target']['text'] == 'old'
    assert 'kind' in item['changedFields'] and 'refs' in item['changedFields']
    source = item['source']['metadataJson']
    cursor = item['source']['metadataNextCharacterOffset']
    while cursor is not None:
        page = execute('episodic_conflict_review', {'sync_id': conflict, 'character_offset': cursor,
            'max_characters': 80, 'review_token': review['reviewToken']}, runtime)
        part = page['differences'][0]['source']
        source += part['metadataJson']; cursor = part['metadataNextCharacterOffset']
    metadata = json.loads(source)
    assert metadata['kind'] == 'preference' and metadata['refs'][0]['id'] == 's' * 300
    assert 'supersededByEpisodeId' in metadata and 'validUntil' in metadata
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_review_includes_target_only_event_collision(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime.episodic_conflict_actions import execute
    conflict = 'episodic-' + '1' * 40
    incoming = {**old, 'episodeId': 'source-new', 'eventId': 'collision', 'text': 'source'}
    local = {**old, 'agentId': assistant['agentId'], 'episodeId': 'target-only',
             'eventId': 'collision', 'text': 'local'}
    archive(conflict, [old, incoming])
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events.append(local); tx._dirty = True
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=conflict)['conflictCount'] == 1
    review = execute('episodic_conflict_review', {'sync_id': conflict},
                     {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']})
    rows = {row['episodeId']: row for row in review['differences']}
    assert rows['source-new']['source']['text'] == 'source'
    assert rows['target-only']['kind'] == 'target_only' and rows['target-only']['target']['text'] == 'local'
    assert 'collision' in rows['target-only']['target']['metadataJson']
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_source_change_requires_new_review_then_keeps_target(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime.episodic_conflict_actions import execute
    conflict = 'episodic-' + '1' * 40
    stale = 'episodic-' + '2' * 40
    refreshed = 'episodic-' + '3' * 40
    final = 'episodic-' + '4' * 40
    archive(conflict, [])
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=conflict)['conflictCount'] == 1
    runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
    review = execute('episodic_conflict_review', {'sync_id': conflict}, runtime)
    changed = {**old, 'text': 'latest source'}
    archive(stale, [changed])
    with owner.admit(**args) as lease:
        try: reconcile_episodic(lease, sync_id=stale, resolve_sync_id=conflict, review_token=review['reviewToken'])
        except MigrationIOError as error: assert str(error) == 'review_changed'
        else: raise AssertionError('changed source was accepted without a new review')
    archive(refreshed, [changed])
    with owner.admit(**args) as lease:
        outcome = reconcile_episodic(lease, sync_id=refreshed)
        assert outcome['appliedCount'] == 0 and outcome['conflictCount'] > 0
    review2 = execute('episodic_conflict_review', {'sync_id': refreshed}, runtime)
    assert review2['differences'][0]['source']['text'] == 'latest source'
    assert review2['differences'][0]['target']['text'] == 'old'
    archive(final, [changed])
    with owner.admit(**args) as lease:
        outcome = reconcile_episodic(lease, sync_id=final, resolve_sync_id=refreshed, review_token=review2['reviewToken'])
        assert outcome['appliedCount'] == outcome['conflictCount'] == 0
    assert episodes.list_episodic_events(assistant['agentId'], include_superseded=True)[0]['text'] == 'old'
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_live_capture_rechecks_review_and_refreshes_changed_source(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from types import SimpleNamespace
    from core.assistant_runtime.migration_io import read_stable_file, verify_snapshot
    from core.assistant_runtime.online_episodic_sync import synchronize_episodic
    from core.assistant_runtime.episodic_conflict_actions import execute
    registry = workspace / 'agents/agents.json'
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({'agents': [{'agentId': 'old-pa', 'directSessionId': 'direct',
        'roleKey': 'personal_assistant', 'status': 'active',
        'metadata': {'personalAssistantProfile': 'personal_assistant_v1'}}]}))
    source = workspace / 'agents/old-pa/events/episodic_events.jsonl'
    source.parent.mkdir(parents=True); source.write_bytes(b'')
    authority = read_stable_file(registry, 16 * 1024 * 1024)
    paths = SimpleNamespace(project_root=project, project_id=scope['projectId'], instance_id=scope['instanceId'])
    binding = (project, workspace, paths, 'old-pa', lambda: verify_snapshot(authority), (authority,))
    def run(mid, **kw):
        return synchronize_episodic(preview_binding=binding, owner=owner, generation='generation', turn_id='turn',
            initial_operation_id=initial, sync_id=mid, **kw)
    conflict = 'episodic-' + '1' * 40
    assert run(conflict)['conflictCount'] == 1
    runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
    review = execute('episodic_conflict_review', {'sync_id': conflict}, runtime)
    changed = {**old, 'text': 'live new source'}
    source.write_bytes(encoded([changed]))
    try: run('episodic-' + '2' * 40, resolve_sync_id=conflict, review_token=review['reviewToken'])
    except MigrationIOError as error: assert str(error) == 'review_changed'
    else: raise AssertionError('changed live source accepted')
    refresh = 'episodic-' + '3' * 40
    assert run(refresh)['conflictCount'] == 1
    fresh = execute('episodic_conflict_review', {'sync_id': refresh}, runtime)
    assert fresh['differences'][0]['source']['text'] == 'live new source'
    assert run('episodic-' + '4' * 40, resolve_sync_id=refresh, review_token=fresh['reviewToken'])['conflictCount'] == 0
    assert episodes.list_episodic_events(assistant['agentId'], include_superseded=True)[0]['text'] == 'old'
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_unchanged_blocked_source_returns_a_reviewable_new_receipt(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from core.assistant_runtime.episodic_conflict_actions import execute
    first = 'episodic-' + '1' * 40
    second = 'episodic-' + '2' * 40
    archive(first, []); archive(second, [])
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=first)['conflictCount'] == 1
        assert reconcile_episodic(lease, sync_id=second)['conflictCount'] == 1
    review = execute('episodic_conflict_review', {'sync_id': second},
                     {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']})
    assert review['syncId'] == second and review['total'] == 1
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)
