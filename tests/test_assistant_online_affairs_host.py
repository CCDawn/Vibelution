"""Private online affairs host contract and generation fences."""

from fastapi.testclient import TestClient
from contextlib import contextmanager
from types import SimpleNamespace

from core.assistant_runtime.host import create_app
from tests.test_assistant_history_host import body, make_host
from tests.test_assistant_history_preview import setup_preview  # noqa: F401
from tests.test_assistant_online_affairs_sync import _SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_completed_sync_cache_evicts_only_after_preview_retirement(tmp_path, monkeypatch):
    from core.assistant_runtime import migration_affairs_conflicts, native, online_affairs_sync
    from core.assistant_runtime.history_host import HistoryHost
    from core.assistant_runtime.migration_io import MigrationIOError

    class Preview:
        def __init__(self):
            self.available = set()
        def consume_for_import(self, preview_id, project_id, revision, turn_id):
            if preview_id not in self.available:
                raise MigrationIOError("history_preview_expired")
            self.available.remove(preview_id)
            return (None, None, SimpleNamespace(project_id="source", instance_id="instance"),
                    "agent", None, ())
        def discard(self, preview_id):
            self.available.discard(preview_id)

    preview = Preview()
    host = HistoryHost(tmp_path, "generation", None, preview)
    blocked = set()
    @contextmanager
    def guard(_generation, _turn, operation):
        if operation in blocked:
            raise MigrationIOError("affairs_sync_busy")
        yield
    monkeypatch.setattr(host, "_sync_guard", guard)
    monkeypatch.setattr(native, "_AGENT_ID", "target")
    target = object()
    target_active = []
    @contextmanager
    def locked_target(root, *, target_agent_id):
        assert native._LOCK._is_owned()
        assert root == tmp_path and target_agent_id == "target"
        target_active.append(target)
        try:
            yield target
        finally:
            target_active.pop()
    def baseline(root, *, source_scope, target_agent_id, target):
        assert native._LOCK._is_owned() and target_active == [target]
        assert root == tmp_path and target_agent_id == "target"
        assert source_scope == {"projectId": "source", "instanceId": "instance", "agentId": "agent"}
        return {"baselineMigrationId": "initial"}
    monkeypatch.setattr(migration_affairs_conflicts, "locked_affairs_target", locked_target)
    monkeypatch.setattr(migration_affairs_conflicts, "discover_affairs_baseline_locked", baseline)
    writes = []
    def synchronize(**kwargs):
        assert not native._LOCK._is_owned() and not target_active
        writes.append(kwargs["migration_id"])
        return {"state": "complete", "code": "synchronized", "appliedCount": 1, "conflictCount": 0}
    monkeypatch.setattr(online_affairs_sync, "synchronize_affairs", synchronize)
    def invoke(n):
        return host.sync_affairs("project", f"{n:064x}", 1, "turn", f"{n:032x}")

    # Rejection before consuming a preview must retire it before eviction.
    preview.available.add(f"{0:064x}")
    blocked.add(f"{0:032x}")
    assert invoke(0)["code"] == "busy"
    assert f"{0:064x}" not in preview.available
    blocked.clear()
    # Cancellation before delivery remains fenced even after cache churn.
    cancelled_preview = f"{9999:064x}"
    cancelled_id = f"{9999:032x}"
    preview.available.add(cancelled_preview)
    assert host.cancel_affairs(cancelled_id, cancelled_preview)["cancelled"]
    for n in range(1, 260):
        preview.available.add(f"{n:064x}")
        assert invoke(n)["state"] == "complete"
    assert len(writes) == 259 and len(host._sync_seen) == 256
    assert invoke(0)["state"] == "unknown"  # The pre-consumption busy result was evicted.
    assert invoke(1)["state"] == "unknown"  # A completed write was evicted, not repeated.
    assert host.cancel_affairs(f"{1:032x}", f"{1:064x}")["cancelled"]
    assert invoke(1)["state"] == "unknown"  # A late cancel cannot erase prior effects.
    assert host.sync_affairs("project", cancelled_preview, 1, "turn", cancelled_id)["state"] == "unknown"
    assert len(writes) == 259
    # A legacy unresolved result with no eligible receipt remains unresolved.
    monkeypatch.setattr(migration_affairs_conflicts, "_sync_candidates", lambda *_args: {})
    monkeypatch.setattr(migration_affairs_conflicts, "_BaselineVerifier",
                        lambda *_args, **_kwargs: SimpleNamespace(candidates=None, finish=lambda: None))
    for n, source_code, expected in [
        (2000, "affairs_baseline_unresolved", "unresolved"),
        (2001, "affairs_baseline_pending", "pending"),
        (2002, "affairs_baseline_not_found", "baseline_unavailable"),
        (2003, "other_failure", "project_unavailable"),
    ]:
        def fail_baseline(*_args, **_kwargs):
            raise MigrationIOError(source_code)
        monkeypatch.setattr(migration_affairs_conflicts, "discover_affairs_baseline_locked", fail_baseline)
        preview.available.add(f"{n:064x}")
        result = invoke(n)
        assert result["state"] == "rejected" and result["code"] == expected
        assert result["readyForCutover"] is False and f"{n:064x}" not in preview.available
    assert len(writes) == 259


def test_sync_cache_never_evicts_unfinished_operations(tmp_path, monkeypatch):
    from core.assistant_runtime.history_host import HistoryHost
    host = HistoryHost(tmp_path, "generation", None, SimpleNamespace(discard=lambda _id: None))
    host._sync_seen = {f"{n:032x}": {"result": None} for n in range(256)}
    result = host.sync_affairs("project", "a" * 64, 1, "turn", "f" * 32)
    assert result["state"] == "rejected" and result["code"] == "busy"
    assert len(host._sync_seen) == 256 and all(row["result"] is None for row in host._sync_seen.values())


def test_private_affairs_endpoint_is_closed_and_never_accepts_approval_or_paths(tmp_path, setup_preview, monkeypatch):
    dispatch, _, history_host, app = make_host(tmp_path, setup_preview)
    request = body(dispatch)
    calls = []
    def synchronize(*values):
        calls.append(values)
        return {'schemaVersion': 1, 'projectId': values[0], 'previewId': values[1],
                'migrationId': 'affairs-' + 'a' * 40, 'state': 'unknown', 'code': 'unknown',
                'readyForCutover': False}
    monkeypatch.setattr(history_host, 'sync_affairs', synchronize)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        assert client.post('/api/assistant/affairs-sync', json=request).status_code == 401
        client.headers['Authorization'] = 'Bearer private-test-token'
        assert client.post('/api/assistant/affairs-sync', json={**request, 'approved': True}).status_code == 422
        assert client.post('/api/assistant/affairs-sync', json={**request, 'sourcePath': 'C:/secret'}).status_code == 422
        assert client.post('/api/assistant/affairs-sync?x=1', json=request).status_code == 422
        response = client.post('/api/assistant/affairs-sync', json=request)
        assert response.status_code == 200 and response.json()['state'] == 'unknown'
        assert len(calls) == 1 and calls[0] == (request['projectId'], request['previewId'],
            request['revision'], request['turnId'], request['operationId'])
        recover_id = 'affairs-' + 'b' * 40
        response = client.post('/api/assistant/affairs-sync', json={**request, 'recoverSyncId': recover_id})
        assert response.status_code == 200 and calls[-1][-1] == recover_id
        for bad in ('affairs-' + 'A' * 40, 'affairs-' + 'a' * 39, '../other', 123):
            assert client.post('/api/assistant/affairs-sync', json={**request, 'recoverSyncId': bad}).status_code == 422
        assert client.post('/api/assistant/history-import', json={**request, 'recoverSyncId': recover_id}).status_code == 422


_HOST_SETUP = _SETUP.split("binding = preview.consume_for_import", 1)[0] + r'''
from core.assistant_runtime.history_host import HistoryHost
from core.assistant_runtime.main_control import affairs_migration_id
from core.web.services import session_service as sessions
history_host = HistoryHost(target, 'generation', dispatch, preview)
with sessions._RUNNING_SESSIONS_LOCK:
    sessions._RUNNING_SESSION_IDS.add(assistant['directSessionId'])
    sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'turn-one'
def sync():
    return history_host.sync_affairs('registered:1', value['previewId'], 1, 'turn-one', 'a' * 32)
def cleanup():
    with sessions._RUNNING_SESSIONS_LOCK:
        sessions._RUNNING_SESSION_IDS.discard(assistant['directSessionId'])
        sessions._SESSION_ACTIVE_TURN_IDS.pop(assistant['directSessionId'], None)
    history_host.close()
    assert native.shutdown()['closed']
'''


def test_actual_online_coordinator_through_current_turn_private_host(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
try:
    result = sync()
    assert result == {'schemaVersion': 1, 'projectId': 'registered:1', 'previewId': value['previewId'],
        'migrationId': affairs_migration_id('registered:1', value['previewId']),
        'readyForCutover': False, 'state': 'complete', 'code': 'synchronized',
        'appliedCount': 1, 'conflictCount': 0}
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'updated'
    assert sync() == result  # Same operation reuses the result, never reruns.
    assert history_host.cancel_affairs('a' * 32, value['previewId'])['cancelled']
    assert sync() == result  # A later fence never erases a committed result.
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_retry_converges_then_later_syncs_preserve_user_edits(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
try:
    user = {**old, 'title': 'user edit'}
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [user])
    first = sync()
    assert first['state'] == 'partial' and first['code'] == 'unresolved' and first['conflictCount'] == 1
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [user]
    # The first retry is still unresolved while the user's value differs.
    again_preview = preview.preview('registered:1', turn_id='turn-one')
    again = history_host.sync_affairs('registered:1', again_preview['previewId'], 1, 'turn-one', 'b' * 32)
    assert again['state'] == 'rejected' and again['code'] == 'unresolved'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [user]
    # User resolves the conflict. A new governed sync may confirm it and
    # apply a later source update without recursively acquiring the Turn lock.
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [{**old, 'title': 'updated'}])
    source.write_bytes(json.dumps({**old, 'title': 'newer'}).encode() + b'\n')
    second_preview = preview.preview('registered:1', turn_id='turn-one')
    second = history_host.sync_affairs('registered:1', second_preview['previewId'], 1, 'turn-one', 'c' * 32)
    assert second['state'] == 'complete' and second['appliedCount'] == 1, second
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'newer'
    # Historical convergence remains valid after the later source update;
    # another local edit is protected by three-way reconciliation.
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [{**old, 'title': 'later user edit'}])
    source.write_bytes(json.dumps({**old, 'title': 'third source'}).encode() + b'\n')
    third_preview = preview.preview('registered:1', turn_id='turn-one')
    third = history_host.sync_affairs('registered:1', third_preview['previewId'], 1, 'turn-one', 'd' * 32)
    assert third['state'] == 'partial' and third['code'] == 'unresolved' and third['conflictCount'] == 1, third
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'later user edit'
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_cancel_fences_inflight_archive_before_acknowledging(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import threading
from concurrent.futures import ThreadPoolExecutor
import core.assistant_runtime.migration_source_archive as archive_module
reached, resume, revoked = threading.Event(), threading.Event(), threading.Event()
original = archive_module._write_new
def pause(*a, **kw):
    reached.set()
    assert resume.wait(8)
    return original(*a, **kw)
archive_module._write_new = pause
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(sync)
        assert reached.wait(8)
        owner = history_host._sync_active['owner']
        original_revoke = owner.revoke
        def mark_revoke():
            result = original_revoke(); revoked.set(); return result
        owner.revoke = mark_revoke
        cancelling = pool.submit(history_host.cancel_affairs, 'a' * 32, value['previewId'])
        assert revoked.wait(3)
        assert not cancelling.done()
        resume.set()
        result = pending.result(timeout=10)
        ack = cancelling.result(timeout=10)
    assert ack == {'schemaVersion': 1, 'operationId': 'a' * 32, 'cancelled': True}
    assert result['state'] == 'unknown' and result['code'] == 'unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
    assert not (target / 'history_sources/migrations' / result['migrationId'] / '.confirmed').exists()
finally:
    resume.set()
    archive_module._write_new = original
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_stale_or_unmatched_turn_never_imports(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
try:
    with sessions._RUNNING_SESSIONS_LOCK:
        sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'other-turn'
    result = sync()
    assert result['state'] == 'rejected' and result['code'] == 'preview_invalid'
    assert not (target / 'history_sources/migrations' / result['migrationId']).exists()
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_native_lock_contention_returns_without_waiting_or_writing(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import threading
acquired, release = threading.Event(), threading.Event()
def hold_native():
    with native._LOCK:
        acquired.set()
        assert release.wait(8)
worker = threading.Thread(target=hold_native)
worker.start()
try:
    assert acquired.wait(5)
    result = sync()
    assert result['state'] == 'rejected' and result['code'] == 'busy'
    assert not (target / 'history_sources/migrations' / result['migrationId']).exists()
finally:
    release.set(); worker.join(timeout=8)
    assert not worker.is_alive()
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_stop_revokes_before_waiting_for_inflight_archive(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import threading
from concurrent.futures import ThreadPoolExecutor
import core.assistant_runtime.migration_source_archive as archive_module
reached, resume, stop_started, native_called, revoked = (threading.Event() for _ in range(5))
original = archive_module._write_new
def pause(*a, **kw):
    reached.set(); assert resume.wait(8)
    return original(*a, **kw)
def request_stop():
    stop_started.set()
    return history_host.stop_native_turn(lambda turn: native_called.set() or {'turnId': turn}, 'turn-one')
archive_module._write_new = pause
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(sync); assert reached.wait(8)
        owner = history_host._sync_active['owner']; original_revoke = owner.revoke
        def mark_revoke():
            result = original_revoke(); revoked.set(); return result
        owner.revoke = mark_revoke
        stopping = pool.submit(request_stop); assert stop_started.wait(3)
        assert revoked.wait(3)
        assert not native_called.is_set()
        resume.set()
        result = pending.result(timeout=10); ack = stopping.result(timeout=10)
    assert ack == {'turnId': 'turn-one'} and native_called.is_set()
    assert result['state'] == 'unknown' and result['code'] == 'unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
finally:
    resume.set(); archive_module._write_new = original; cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_registry_revocation_fences_inflight_archive(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import threading
from concurrent.futures import ThreadPoolExecutor
import core.assistant_runtime.migration_source_archive as archive_module
reached, resume, revoke_started, updated, revoked = (threading.Event() for _ in range(5))
original = archive_module._write_new
def pause(*a, **kw):
    reached.set(); assert resume.wait(8)
    return original(*a, **kw)
def revoke():
    revoke_started.set()
    history_host.signal_registry_change()
    with history_host.guard():
        history_host.registry_changed()
        dispatch.replace_projects({'schemaVersion': 1, 'revision': 2, 'projects': {}})
    updated.set()
archive_module._write_new = pause
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(sync); assert reached.wait(8)
        owner = history_host._sync_active['owner']; original_revoke = owner.revoke
        def mark_revoke():
            result = original_revoke(); revoked.set(); return result
        owner.revoke = mark_revoke
        revoking = pool.submit(revoke); assert revoke_started.wait(3)
        assert revoked.wait(3)
        assert not updated.is_set()
        resume.set()
        result = pending.result(timeout=10); revoking.result(timeout=10)
    assert updated.is_set() and result['state'] == 'unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
finally:
    resume.set(); archive_module._write_new = original; cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_lost_ledger_readback_reports_unknown_after_possible_commit(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import core.assistant_runtime.migration_affairs_sync as sync_module
from core.assistant_runtime.migration_io import MigrationIOError
original_write, original_read = sync_module._replace_ledger, sync_module.read_stable_file
committed = [False]
def write_then_record(*a, **kw):
    original_write(*a, **kw); committed[0] = True
def fail_readback(path, *a, **kw):
    if committed[0] and path.name == 'items.jsonl':
        raise MigrationIOError('synthetic_readback_loss')
    return original_read(path, *a, **kw)
sync_module._replace_ledger, sync_module.read_stable_file = write_then_record, fail_readback
try:
    result = sync()
    assert result['state'] == 'unknown' and result['code'] == 'unknown'
    assert 'appliedCount' not in result and 'conflictCount' not in result
    assert committed[0] and service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'updated'
finally:
    sync_module._replace_ledger, sync_module.read_stable_file = original_write, original_read
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_recover_pending_receipt_only_with_matching_authority_and_ledger(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import core.assistant_runtime.migration_affairs_sync as sync_module
original_write = sync_module._replace_ledger
def fail_before_commit(*args, **kwargs):
    raise RuntimeError('interrupted before ledger write')
sync_module._replace_ledger = fail_before_commit
try:
    first = sync()
    assert first['state'] == 'unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl') == [old]
    mid = first['migrationId']
    path = target / 'affairs_sync_receipts' / (hashlib.sha256(mid.encode()).hexdigest() + '.json')
    receipt = path.read_bytes()
    assert json.loads(receipt)['published'] is False
    sync_module._replace_ledger = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('ledger rewrite'))
    def recover(op, recover_id=mid):
        p = preview.preview('registered:1', turn_id='turn-one')
        return history_host.sync_affairs('registered:1', p['previewId'], 1, 'turn-one', op, recover_id)
    # A fresh preview for another source identity cannot recover this record.
    registry_raw = registry.read_text()
    registry.write_text(registry_raw.replace('old-pa', 'other-pa'))
    assert recover('1' * 32)['state'] == 'unknown'
    registry.write_text(registry_raw)
    # Revoked source authority cannot confirm a pending receipt.
    p = preview.preview('registered:1', turn_id='turn-one')
    registry.write_text(registry_raw + ' ')
    invalid = history_host.sync_affairs('registered:1', p['previewId'], 1, 'turn-one', '2' * 32, mid)
    assert invalid['state'] != 'complete' and json.loads(path.read_bytes())['published'] is False
    registry.write_text(registry_raw)
    # Missing receipts and a mismatching target are never evidence of success.
    path.unlink()
    assert recover('b' * 32)['state'] == 'unknown'
    assert not path.exists()
    path.write_bytes(receipt)
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [old])
    assert recover('c' * 32)['state'] == 'unknown'
    assert json.loads(path.read_bytes())['published'] is False
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [{**old, 'title': 'updated'}])
    result = recover('d' * 32)
    assert result['migrationId'] == mid and result['state'] == 'confirmed' and result['code'] == 'matched'
    assert result['conflictCount'] == 0 and 'appliedCount' not in result
    assert result['readyForCutover'] is False and json.loads(path.read_bytes())['published'] is True
    from core.assistant_runtime.affairs_conflict_actions import _sync_receipt_status
    status = _sync_receipt_status(target, mid, assistant['agentId'])
    assert status['state'] == 'published' and status['plannedAppliedCount'] == 1 and 'appliedCount' not in status
    # A published receipt can be reread without replaying the write.
    again = recover('e' * 32)
    assert again['state'] == 'confirmed' and again['migrationId'] == mid and 'appliedCount' not in again
    # An edited ledger no longer proves the digest even if the receipt was published.
    service.store.write_jsonl(assistant['agentId'], 'affairs/items.jsonl', [{**old, 'title': 'user edit'}])
    assert recover('3' * 32)['state'] == 'unknown'
    assert service.store.read_jsonl(assistant['agentId'], 'affairs/items.jsonl')[0]['title'] == 'user edit'
    assert recover('f' * 32, 'affairs-' + 'f' * 40)['state'] == 'unknown'
finally:
    sync_module._replace_ledger = original_write
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_recovery_operation_binding_and_revocation(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import threading
from concurrent.futures import ThreadPoolExecutor
import core.assistant_runtime.migration_affairs_sync as sync_module
original_write, original_reconcile = sync_module._replace_ledger, sync_module.reconcile_affairs
def fail_after_commit(*args, **kwargs):
    original_write(*args, **kwargs); raise RuntimeError('lost acknowledgement')
sync_module._replace_ledger = fail_after_commit
reached, resume = threading.Event(), threading.Event()
try:
    first = sync(); mid = first['migrationId']
    assert first['state'] == 'unknown'
    path = target / 'affairs_sync_receipts' / (hashlib.sha256(mid.encode()).hexdigest() + '.json')
    sync_module._replace_ledger = original_write
    p = preview.preview('registered:1', turn_id='turn-one')
    def paused(*a, **kw):
        reached.set(); assert resume.wait(8)
        return original_reconcile(*a, **kw)
    sync_module.reconcile_affairs = paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(history_host.sync_affairs, 'registered:1', p['previewId'], 1, 'turn-one', 'b' * 32, mid)
        assert reached.wait(8)
        owner = history_host._sync_active['owner']
        revoked = threading.Event(); original_revoke = owner.revoke
        def mark_revoke():
            result = original_revoke(); revoked.set(); return result
        owner.revoke = mark_revoke
        cancelling = pool.submit(history_host.cancel_affairs, 'b' * 32, p['previewId'])
        assert revoked.wait(3) and not cancelling.done()
        resume.set()
        assert pending.result(timeout=10)['state'] == 'unknown'
        assert cancelling.result(timeout=10)['cancelled']
    assert json.loads(path.read_bytes())['published'] is False
    # Same operation ID cannot be rebound to a different recovery ID.
    rebound = history_host.sync_affairs('registered:1', p['previewId'], 1, 'turn-one', 'b' * 32, 'affairs-' + 'f' * 40)
    assert rebound['state'] == 'unknown'
finally:
    resume.set()
    sync_module._replace_ledger, sync_module.reconcile_affairs = original_write, original_reconcile
    cleanup()
''', config_text=TEST_MODEL_CONFIG)
