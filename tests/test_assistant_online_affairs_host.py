"""Private online affairs host contract and generation fences."""

from fastapi.testclient import TestClient
import pytest
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
        def retire(self, preview_id):
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


def test_initial_queue_consumes_only_live_claimed_preview_and_returns_private_binding(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio
import httpx
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.host import create_app
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    project_id, preview_id, category = 'registered:1', value['previewId'], 'personal'
    op = initial_migration_id(project_id, preview_id, category)
    request = {'projectId': project_id, 'previewId': preview_id, 'turnId': 'turn-one',
               'category': category, 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    body = {**request, 'revision': 1, 'deliveryId': wire['deliveryId']}
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1') as client:
            assert (await client.post('/api/assistant/initial-migration/prepare', json=body)).status_code == 401
            client.headers['Authorization'] = 'Bearer private-test-token'
            assert (await client.post('/api/assistant/initial-migration/prepare', json={**body, 'approved': True})).status_code == 422
            assert (await client.post('/api/assistant/initial-migration/prepare', json={**body, 'deliveryId': 'f'*32})).status_code == 409
            result = await client.post('/api/assistant/initial-migration/prepare', json=body)
            assert result.status_code == 200, result.text
            bound = result.json()
            assert bound['sourceScope'] == scope and bound['operationId'] == op and bound['revision'] == 1
            assert bound['targetAgentId'] == assistant['agentId'] and bound['targetSessionId'] == assistant['directSessionId']
            assert bound['authority'] == 'native_policy_admitted' and bound['readyForCutover'] is False
            assert all(len(bound[key]) == 64 for key in ('sourceIdentityDigest', 'registryDigest', 'targetIdentityDigest'))
            assert all(int(bound['projectDirectory'][key]) > 0 for key in ('device', 'inode', 'birthtimeNs'))
            assert str(project) not in result.text and str(workspace) not in result.text and str(target) not in result.text
            from core.assistant_runtime.initial_migration_binding import read_initial_intent, list_initial_intents, publish_initial_intent
            from core.assistant_runtime.migration_io import MigrationIOError
            assert read_initial_intent(target, op) == bound
            assert list_initial_intents(target) == [{'operationId': op, 'registeredProjectId': project_id, 'category': category,
                                                     'registryDigest': bound['registryDigest']}]
            # Re-registration must not mint a second execution authority for
            # the same source, target and category even with a different ID.
            other = {**bound, 'registeredProjectId': 'registered:2',
                     'operationId': initial_migration_id('registered:2', preview_id, category)}
            class Token:
                def publish(self, writer): return writer()
            try:
                publish_initial_intent(target, other, Token(), lambda: None)
            except MigrationIOError as error:
                assert str(error) == 'initial_intent_exists'
            else:
                raise AssertionError('duplicate source was accepted')
            invalid = target / 'initial_migration_intents' / ('e' * 64)
            invalid.mkdir()
            (invalid / 'intent.json').write_text('{"schemaVersion":1}', encoding='utf-8')
            try:
                read_initial_intent(target, op)
            except MigrationIOError:
                pass
            else:
                raise AssertionError('corrupt intent was accepted')
            try:
                list_initial_intents(target)
            except MigrationIOError:
                pass
            else:
                raise AssertionError('corrupt intent was listed')
            (invalid / 'intent.json').unlink()
            invalid.rmdir()
            assert (await client.post('/api/assistant/initial-migration/prepare', json=body)).status_code == 409
        public = {'schemaVersion': 1, 'projectId': project_id, 'previewId': preview_id, 'category': category,
                  'operationId': op, 'state': 'queued', 'code': 'queued', 'readyForCutover': False}
        assert broker.settle(wire['deliveryId'], public)
        assert await task == public
        assert not (target / 'affairs_migrations' / (hashlib.sha256(op.encode()).hexdigest() + '.json')).exists()
    finally:
        broker.close()
try:
    asyncio.run(run_case())
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_one_preview_history_then_both_independently_admitted_initial_intents(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio
import httpx
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.host import create_app
from tests.test_assistant_migration_history import journal, write_json
write_json(workspace / 'chat/chat_state.json', {'conversations': [{'id': 'direct', 'agent_id': 'old-pa'}]})
journal(workspace, 'direct')
value = preview.preview('registered:1', turn_id='turn-one')
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=5, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    token = value['previewId']
    result = history_host.import_history('registered:1', token, 1, 'turn-one', '1' * 32)
    assert result['state'] == 'published', result
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                     headers={'Authorization': 'Bearer private-test-token'}) as client:
            for category in ('personal', 'knowledge'):
                op = initial_migration_id('registered:1', token, category)
                request = {'projectId': 'registered:1', 'previewId': token, 'turnId': 'turn-one',
                           'category': category, 'operationId': op}
                # A preview is not authority: each category needs its own live delivery.
                assert (await client.post('/api/assistant/initial-migration/prepare',
                    json={**request, 'revision': 1, 'deliveryId': 'f' * 32})).status_code == 409
                task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
                wire = (await broker.claim())['request']
                body = {**request, 'revision': 1, 'deliveryId': wire['deliveryId']}
                response = await client.post('/api/assistant/initial-migration/prepare', json=body)
                assert response.status_code == 200, response.text
                assert read_initial_intent(target, op)['category'] == category
                assert (await client.post('/api/assistant/initial-migration/prepare', json=body)).status_code == 409
                public = {'schemaVersion': 1, 'projectId': 'registered:1', 'previewId': token,
                          'category': category, 'operationId': op, 'state': 'queued', 'code': 'queued',
                          'readyForCutover': False}
                assert broker.settle(wire['deliveryId'], public)
                assert await task == public
    finally:
        broker.close()
try:
    asyncio.run(run_case())
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('mode', ['before_admit', 'published', 'expired_before_admit', 'expired_published'])
def test_initial_drain_retires_only_its_issued_preview(tmp_path, mode):
    _run(tmp_path, _HOST_SETUP + '\nmode = ' + repr(mode) + r'''
import asyncio
import httpx
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.migration_io import MigrationIOError
from core.assistant_runtime.host import create_app
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=5, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    token = value['previewId']
    other = preview.preview('registered:1', turn_id='turn-one')['previewId']
    op = initial_migration_id('registered:1', token, 'personal')
    request = {'projectId': 'registered:1', 'previewId': token, 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    delivery = wire['deliveryId']
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                     headers={'Authorization': 'Bearer private-test-token'}) as client:
            if mode.endswith('published'):
                result = await client.post('/api/assistant/initial-migration/prepare',
                    json={**request, 'revision': 1, 'deliveryId': delivery})
                assert result.status_code == 200, result.text
            if mode.startswith('expired'):
                broker._pending[delivery].deadline = 0
                broker._expire()
                assert (await task)['state'] == 'unknown'
            bad = await client.post('/api/assistant/initial-migration/drain',
                json={'deliveryId': delivery, 'operationId': 'initial-' + 'f' * 40})
            assert bad.status_code == 503 and bad.json()['drained'] is False
            if not mode.startswith('expired'):
                assert preview.verify_preview(token)['previewId'] == token
            assert preview.verify_preview(other)['previewId'] == other
            good = await client.post('/api/assistant/initial-migration/drain',
                json={'deliveryId': delivery, 'operationId': op})
            assert good.status_code == 200 and good.json()['drained'] is True
            assert (await task)['state'] == 'unknown'
            try: preview.consume_for_import(token, 'registered:1', 1, 'turn-one', purpose='knowledge')
            except MigrationIOError: pass
            else: raise AssertionError('drained preview remained usable')
            assert preview.verify_preview(other)['previewId'] == other
    finally:
        broker.close()
try:
    asyncio.run(run_case())
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_reauthorizes_unclaimed_intent_after_model_change_but_not_after_claim(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio
import httpx
from core.infrastructure.file_lock import cross_process_file_lock
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent, list_initial_intents
from core.assistant_runtime.host import create_app
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        async def prepare(p):
            request = {'projectId': 'registered:1', 'previewId': p['previewId'], 'turnId': 'turn-one',
                       'category': 'personal', 'operationId': op}
            task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
            wire = (await broker.claim())['request']
            result = await client.post('/api/assistant/initial-migration/prepare',
                json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']})
            if result.status_code == 200:
                settled = {'schemaVersion': 1, **{k: request[k] for k in ('projectId','previewId','category','operationId')},
                           'state': 'queued', 'code': 'queued', 'readyForCutover': False}
                assert broker.settle(wire['deliveryId'], settled)
                assert (await task)['state'] == 'queued'
            else:
                broker.cancel_history_imports('turn-one')
                assert (await task)['state'] == 'unknown'
            return result
        first = await prepare(value)
        assert first.status_code == 200, first.text
        old = first.json()
        original_file = next((target / 'initial_migration_intents').glob('*/intent.json'))
        original_bytes = original_file.read_bytes()
        config = Path(os.environ['VIBELUTION_CONFIG_PATH'])
        config.write_text(config.read_text().replace('context_window = 8192', 'context_window = 16384'))
        from core.assistant_runtime.initial_migration_binding import publish_initial_intent
        from core.assistant_runtime.migration_io import MigrationIOError
        class NoOwnerToken:
            def publish(self, writer): return writer()
            def check(self): pass
        try:
            publish_initial_intent(target, {**old, 'turnId': 'turn-two'}, NoOwnerToken(), lambda: None)
        except MigrationIOError as error:
            assert str(error) == 'initial_profile_owner_unavailable'
        else:
            raise AssertionError('refresh without profile owner was accepted')
        assert read_initial_intent(target, op) == old
        newer = preview.preview('registered:1', turn_id='turn-one')
        second = await prepare(newer)
        assert second.status_code == 200, second.text
        current = second.json()
        assert current['operationId'] == op and current['registryDigest'] != old['registryDigest']
        assert read_initial_intent(target, op) == current
        assert original_file.read_bytes() == original_bytes
        assert list_initial_intents(target) == [{'operationId': op, 'registeredProjectId': 'registered:1', 'category': 'personal',
                                                 'registryDigest': current['registryDigest']}]
        # A second valid successor to the same predecessor is ambiguous, even
        # when both records have valid hashes and matching identity.
        from core.assistant_runtime.initial_migration_binding import _digest
        from core.assistant_runtime.migration_io import MigrationIOError
        chain = next((target / 'initial_migration_intent_refreshes').iterdir())
        record_path = next(chain.glob('*/intent.json'))
        record = json.loads(record_path.read_text())
        fork = {**record, 'binding': {**record['binding'], 'turnId': 'other-turn'}}
        fork_dir = chain / _digest(fork)
        fork_dir.mkdir()
        (fork_dir / 'intent.json').write_text(json.dumps(fork), encoding='utf-8')
        try:
            read_initial_intent(target, op)
        except MigrationIOError:
            pass
        else:
            raise AssertionError('forked intent chain was accepted')
        (fork_dir / 'intent.json').unlink()
        fork_dir.rmdir()
        # A claim observed at the final commit check cannot publish a refresh.
        import scripts.assistant_migration_activate as activate
        from core.assistant_runtime.initial_migration_binding import publish_initial_intent
        original_check = activate._initial_receipts_or_claim
        calls = []
        def claim_race(*args):
            calls.append(1)
            return len(calls) == 2
        class Token:
            def publish(self, writer): return writer()
            def check(self): pass
        activate._initial_receipts_or_claim = claim_race
        try:
            publish_initial_intent(target, {**current, 'turnId': 'turn-two'}, Token(), lambda: None,
                                   owner_check=lambda: True)
        except MigrationIOError as error:
            assert str(error) == 'initial_intent_claimed_unknown'
        else:
            raise AssertionError('claim race allowed a refresh')
        finally:
            activate._initial_receipts_or_claim = original_check
        assert len(calls) == 2 and read_initial_intent(target, op) == current
        (target / 'initial_migration_claims' / op).mkdir(parents=True)
        config.write_text(config.read_text().replace('context_window = 16384', 'context_window = 32768'))
        final = await prepare(preview.preview('registered:1', turn_id='turn-one'))
        assert final.status_code == 409
        assert read_initial_intent(target, op) == current
    broker.close()
try:
    with cross_process_file_lock(target / 'host-owner', timeout=0):
        history_host._initial_owner_check = lambda: True
        asyncio.run(run_case())
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('mode', ['stop', 'registry', 'registry_update'])
def test_initial_endpoint_revokes_before_guard_wait(tmp_path, mode):
    _run(tmp_path, _HOST_SETUP + '\nmode = ' + repr(mode) + r'''
import asyncio, threading
from types import SimpleNamespace
import httpx
import core.assistant_runtime.migration_history as migration_history
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent, list_initial_intents
from core.assistant_runtime.host import create_app
reached, resume = threading.Event(), threading.Event()
original = migration_history._write_new
def blocked(*args, **kwargs):
    original(*args, **kwargs)
    reached.set()
    assert resume.wait(8)
migration_history._write_new = blocked
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    fake_native = SimpleNamespace(stop=lambda turn: {'turnId': turn, 'stopped': True})
    app = create_app(native=fake_native, token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        preparing = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']}))
        assert await asyncio.to_thread(reached.wait, 8)
        if mode == 'stop':
            stopping = asyncio.create_task(client.post('/api/assistant/stop', json={'turnId': 'turn-one'}))
        elif mode == 'registry':
            stopping = asyncio.create_task(client.post('/api/assistant/project-registry/suspend', json={}))
        else:
            stopping = asyncio.create_task(client.put('/api/assistant/project-registry',
                json={'schemaVersion': 1, 'revision': 2, 'projects': {}}))
        async def revoked():
            while not next(iter(broker._initial_tokens))._revoked.is_set():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(revoked(), 2)
        assert (await asyncio.wait_for(client.get('/health'), 1)).status_code == 200
        assert not stopping.done()
        resume.set()
        assert (await preparing).status_code == 409
        assert (await stopping).status_code == (202 if mode == 'stop' else 200)
        assert (await task)['state'] == 'unknown'
        assert read_initial_intent(target, op) is None
        assert list_initial_intents(target) == []
    broker.close()
try:
    asyncio.run(run_case())
finally:
    resume.set()
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_intent_cancel_before_publication_never_authorizes(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading
import httpx
import core.assistant_runtime.migration_history as migration_history
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.host import create_app
reached, resume = threading.Event(), threading.Event()
original = migration_history._write_new
def blocked(*args, **kwargs):
    original(*args, **kwargs)
    reached.set()
    assert resume.wait(8)
migration_history._write_new = blocked
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        preparing = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']}))
        assert await asyncio.to_thread(reached.wait, 8)
        broker.cancel_history_imports('turn-one')
        resume.set()
        assert (await preparing).status_code == 409
        assert (await task)['state'] == 'unknown'
        assert read_initial_intent(target, op) is None
    broker.close()
try:
    asyncio.run(run_case())
finally:
    resume.set()
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_endpoint_times_out_without_claiming_stop_when_commit_is_busy(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading
from types import SimpleNamespace
import httpx
import core.assistant_runtime.migration_io as migration_io
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.host import create_app
reached, resume, called = threading.Event(), threading.Event(), threading.Event()
original = migration_io.publish_directory
def blocked(*args, **kwargs):
    reached.set()
    assert resume.wait(8)
    return original(*args, **kwargs)
migration_io.publish_directory = blocked
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    fake_native = SimpleNamespace(stop=lambda turn: called.set() or {'turnId': turn, 'stopped': True})
    app = create_app(native=fake_native, token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        preparing = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']}))
        assert await asyncio.to_thread(reached.wait, 8)
        stopping = asyncio.create_task(client.post('/api/assistant/stop', json={'turnId': 'turn-one'}))
        assert (await asyncio.wait_for(client.get('/health'), 1)).status_code == 200
        assert (await asyncio.wait_for(stopping, 4)).status_code == 503
        assert not called.is_set()
        assert (await task)['state'] == 'unknown'
        resume.set()
        assert (await preparing).status_code == 409
        assert read_initial_intent(target, op)['operationId'] == op
    broker.close()
try:
    asyncio.run(run_case())
finally:
    resume.set()
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_prepare_drain_waits_for_expired_delivery_worker(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading
import httpx
import core.assistant_runtime.migration_history as migration_history
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.host import create_app
reached, resume = threading.Event(), threading.Event()
original = migration_history._write_new
def blocked(*args, **kwargs):
    original(*args, **kwargs)
    reached.set()
    assert resume.wait(12)
migration_history._write_new = blocked
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    delivery = wire['deliveryId']
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        preparing = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'revision': 1, 'deliveryId': delivery}))
        assert await asyncio.to_thread(reached.wait, 8)
        preparing.cancel()  # Aborting the HTTP waiter does not stop its thread.
        try:
            await preparing
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('prepare request was not interrupted')
        broker._pending[delivery].deadline = 0
        broker._expire()
        assert (await task)['state'] == 'unknown'
        assert delivery not in broker._pending
        wrong = await client.post('/api/assistant/initial-migration/drain',
            json={'deliveryId': delivery, 'operationId': 'initial-' + 'f' * 40})
        assert wrong.status_code == 503 and wrong.json()['drained'] is False
        draining = asyncio.create_task(client.post('/api/assistant/initial-migration/drain',
            json={'deliveryId': delivery, 'operationId': op}))
        assert (await asyncio.wait_for(client.get('/health'), 1)).status_code == 200
        first = await asyncio.wait_for(draining, 4)
        assert first.status_code == 503 and first.json() == {
            'schemaVersion': 1, 'operationId': op, 'state': 'unknown', 'drained': False}
        draining = asyncio.create_task(client.post('/api/assistant/initial-migration/drain',
            json={'deliveryId': delivery, 'operationId': op}))
        await asyncio.sleep(0.05)
        assert not draining.done()
        resume.set()
        result = await asyncio.wait_for(draining, 4)
        assert result.status_code == 200 and result.json() == {
            'schemaVersion': 1, 'operationId': op, 'state': 'unknown', 'drained': True}
        assert read_initial_intent(target, op) is None
        assert (await client.post('/api/assistant/initial-migration/drain?x=1',
            json={'deliveryId': delivery, 'operationId': op})).status_code == 422
    broker.close()
try:
    asyncio.run(run_case())
finally:
    resume.set()
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_intent_lost_confirmation_recovers_same_id(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio
import httpx
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import read_initial_intent
from core.assistant_runtime.host import create_app
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    original = broker.initial_delivery
    def interrupted(delivery, request, **kwargs):
        if kwargs.get('confirm'):
            broker.cancel_history_imports('turn-one')
            return False
        return original(delivery, request, **kwargs)
    broker.initial_delivery = interrupted
    op = initial_migration_id('registered:1', value['previewId'], 'personal')
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'personal', 'operationId': op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1',
                                 headers={'Authorization': 'Bearer private-test-token'}) as client:
        result = await client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']})
        assert result.status_code == 409
        assert (await task)['state'] == 'unknown'
        assert read_initial_intent(target, op)['operationId'] == op
    broker.close()
try:
    asyncio.run(run_case())
finally:
    cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_initial_prepare_refuses_changed_authority_or_inactive_turn(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
from core.assistant_runtime.main_control import initial_migration_id
from core.assistant_runtime.migration_io import MigrationIOError
def prepare(p, turn='turn-one'):
    return history_host.prepare_initial_source('registered:1', p['previewId'], 1, turn,
        initial_migration_id('registered:1', p['previewId'], 'knowledge'), 'knowledge', None)
try:
    original = registry.read_text()
    registry.write_text(original + ' ')
    try: prepare(value)
    except MigrationIOError: pass
    else: raise AssertionError('changed source was accepted')
    registry.write_text(original)
    fresh = preview.preview('registered:1', turn_id='turn-one')
    with sessions._RUNNING_SESSIONS_LOCK:
        sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'other-turn'
    try: prepare(fresh)
    except MigrationIOError: pass
    else: raise AssertionError('inactive turn was accepted')
    with sessions._RUNNING_SESSIONS_LOCK:
        sessions._SESSION_ACTIVE_TURN_IDS[assistant['directSessionId']] = 'turn-one'
    try: prepare(fresh)
    except MigrationIOError: pass
    else: raise AssertionError('failed preview was replayed')
    assert not (target / 'knowledge_migrations').exists()
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
