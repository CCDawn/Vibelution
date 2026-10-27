"""Isolated native coordinator tests; there is no public host wiring here."""

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_SETUP = r'''
import hashlib, json, os
from contextlib import contextmanager
from pathlib import Path
from core.assistant_runtime import native
from core.assistant_runtime.dispatch import DispatchService
from core.assistant_runtime.history_preview import HistoryPreview
from core.assistant_runtime.online_affairs_sync import synchronize_affairs
from core.assistant_runtime.online_affairs_sync_lease import OnlineAffairsSyncOwner
from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path

home = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).parent
target = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
assistant = native.bootstrap(target)['assistant']
project = home / 'source-project'
(project / '.vibelution').mkdir(parents=True)
(project / '.vibelution/project.json').write_text(json.dumps({'schemaVersion': 1, 'projectId': 'fixture-project'}))
paths = resolve_project_storage_paths(project)
marker = storage_migration_state_path(paths)
marker.parent.mkdir(parents=True)
marker.write_text(json.dumps({'schemaVersion': 1, 'status': 'completed',
    'projectId': paths.project_id, 'instanceId': paths.instance_id}))
workspace = paths.data / 'workspace'
registry = workspace / 'agents/agents.json'
registry.parent.mkdir(parents=True)
registry.write_text(json.dumps({'agents': [{'agentId': 'old-pa', 'directSessionId': 'direct',
    'roleKey': 'personal_assistant', 'status': 'active',
    'metadata': {'personalAssistantProfile': 'personal_assistant_v1'}}]}))
scope = {'projectId': paths.project_id, 'instanceId': paths.instance_id, 'agentId': 'old-pa'}
source = workspace / 'agents/old-pa/plugins/personal-affairs/affairs/items.jsonl'
source.parent.mkdir(parents=True)
old = {'schemaVersion': 1, 'itemId': 'item', 'kind': 'todo', 'title': 'old',
       'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
raw = json.dumps(old).encode() + b'\n'
source.write_bytes(raw)
memory = workspace / 'agents/old-pa/memory/private.txt'
memory.parent.mkdir(parents=True)
memory.write_bytes(b'PRIVATE_UNRELATED_MEMORY')
archive = target / 'history_sources/migrations/initial'
baseline = archive / 'sources/mps-ref/affairs/items.jsonl'
baseline.parent.mkdir(parents=True)
baseline.write_bytes(raw)
digest = hashlib.sha256(raw).hexdigest()
(archive / 'manifest.json').write_text(json.dumps({'schemaVersion': 2, 'migrationId': 'initial',
    'sourceScope': scope, 'readOnly': True, 'untrustedContent': True, 'entries': [{
    'sourceRef': 'mps-ref', 'category': 'personal_affairs',
    'path': 'sources/mps-ref/affairs/items.jsonl', 'sha256': digest, 'size': len(raw)}]}))
(archive / '.confirmed').mkdir()
receipts = target / 'affairs_migrations'
receipts.mkdir()
(receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).write_text(json.dumps({
    'schemaVersion': 1, 'migrationId': 'initial', 'sourceScope': scope,
    'sourceSha256': digest, 'targetAgentId': assistant['agentId'], 'itemCount': 1, 'published': True}))
from core.web.services import personal_affairs_service
service = personal_affairs_service.get_personal_affairs_service()
service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [old])
source.write_bytes(json.dumps({**old, 'title': 'updated'}).encode() + b'\n')
dispatch = DispatchService(target, {})
dispatch.replace_projects({'schemaVersion': 1, 'revision': 1, 'projects': {'registered:1': str(project)}})
preview = HistoryPreview(dispatch, Path(os.environ['VIBELUTION_CONFIG_PATH']))
value = preview.preview('registered:1', turn_id='turn-one')
binding = preview.consume_for_import(value['previewId'], 'registered:1', 1, 'turn-one')
@contextmanager
def trusted_test_guard(generation, turn):
    assert (generation, turn) == ('generation', 'turn-one')
    yield
owner = OnlineAffairsSyncOwner('generation', trusted_test_guard)
args = dict(preview_binding=binding, owner=owner, generation='generation', turn_id='turn-one',
            migration_id='sync-one', baseline_migration_id='initial')
'''


def test_online_sync_uses_only_affairs_and_keeps_existing_offline_capture_behavior(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    from scripts.assistant_migration_activate import _capture
    import core.assistant_runtime.migration_paths as routing
    # Default capture retains its existing full-source behavior.
    default, _ = _capture(project, workspace, scope, None)
    assert any(row['category'] == 'memory' and row['status'] == 'available' for row in default.report['sources'])
    original = routing.fingerprint_tree
    def only_affairs(path, **kwargs):
        assert Path(path) == source.parent.parent
        return original(path, **kwargs)
    routing.fingerprint_tree = only_affairs
    try:
        result = synchronize_affairs(**args)
    finally:
        routing.fingerprint_tree = original
    assert result['state'] == 'complete' and result['appliedCount'] == 1
    assert result['conflictCount'] == 0 and result['archivePublished']
    assert not result['sourceQuiesced'] and not result['readyForCutover']
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'updated'
    manifest = json.loads((target / 'history_sources/migrations/sync-one/manifest.json').read_text())
    assert {entry['category'] for entry in manifest['entries']} == {'personal_affairs'}
    assert memory.read_bytes() == b'PRIVATE_UNRELATED_MEMORY'
    assert owner.drained()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_revocation_during_archive_write_is_unknown_and_never_starts_sync(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    import core.assistant_runtime.migration_source_archive as archive_module
    original = archive_module._write_new
    def revoke_during_write(*args, **kwargs):
        assert owner.revoke() is False
        return original(*args, **kwargs)
    archive_module._write_new = revoke_during_write
    try:
        result = synchronize_affairs(**args)
    finally:
        archive_module._write_new = original
    assert result['state'] == 'unknown' and result['code'] == 'archive_outcome_unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
    assert not (target / 'history_sources/migrations/sync-one/.confirmed').exists()
    # The locked baseline check may create its empty lock directory, but no
    # synchronization receipt or ledger write may have been published.
    assert not list((target / 'affairs_sync_receipts').glob('*.json')) and owner.drained()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_prepare_failure_preserves_confirmed_archive_as_partial(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    import core.assistant_runtime.migration_affairs_conflicts as conflicts
    original = conflicts.prepare_affairs_conflicts
    def fail_prepare(*args, **kwargs):
        raise RuntimeError('synthetic preparation failure')
    conflicts.prepare_affairs_conflicts = fail_prepare
    try:
        result = synchronize_affairs(**args)
    finally:
        conflicts.prepare_affairs_conflicts = original
    assert result['state'] == 'partial' and result['code'] == 'difference_outcome_unknown'
    assert result['archivePublished'] and (target / 'history_sources/migrations/sync-one/.confirmed').is_dir()
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_unknown_ledger_result_requires_explicit_same_id_reconciliation(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    import core.assistant_runtime.migration_affairs_sync as sync_module
    original = sync_module._replace_ledger
    def fail_after_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic lost acknowledgement')
    sync_module._replace_ledger = fail_after_commit
    try:
        result = synchronize_affairs(**args)
    finally:
        sync_module._replace_ledger = original
    assert result['state'] == 'unknown' and result['code'] == 'sync_outcome_unknown'
    assert result['archivePublished'] and owner.drained()
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'updated'
    receipt_path = target / 'affairs_sync_receipts' / (hashlib.sha256(b'sync-one').hexdigest() + '.json')
    assert json.loads(receipt_path.read_text())['published'] is False
    # Explicit trusted reconciliation inspects the same ID and must not write
    # the ledger again; it is not an automatic new-ID retry.
    def no_rewrite(*args, **kwargs):
        raise AssertionError('pending receipt retried the write')
    sync_module._replace_ledger = no_rewrite
    try:
        with owner.admit(generation='generation', turn_id='turn-one',
                baseline_migration_id='initial', source_scope=scope) as lease:
            recovered = sync_module.reconcile_affairs(lease, sync_id='sync-one', source_scope=scope)
    finally:
        sync_module._replace_ledger = original
    assert recovered['reused'] and json.loads(receipt_path.read_text())['published'] is True
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_missing_initial_import_receipt_rejects_without_publication(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    (receipts / (hashlib.sha256(b'initial').hexdigest() + '.json')).unlink()
    result = synchronize_affairs(**args)
    assert result['state'] == 'rejected' and result['code'] == 'source_or_authority_unavailable'
    assert not (target / 'history_sources/migrations/sync-one').exists()
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_changed_source_registry_rejects_consumed_preview_without_publication(tmp_path):
    _run(tmp_path, _SETUP + r'''
try:
    # The trusted preview is consumed, then its registry authority changes
    # before the transaction is admitted. It must not be rebound silently.
    registry.write_text(registry.read_text() + ' ')
    result = synchronize_affairs(**args)
    assert result['state'] == 'rejected' and result['code'] == 'source_or_authority_unavailable'
    assert not (target / 'history_sources/migrations/sync-one').exists()
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)
