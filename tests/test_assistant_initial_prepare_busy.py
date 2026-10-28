"""Lock contention cannot be confused with an uncertain publication."""
from tests.test_assistant_online_affairs_host import _HOST_SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_real_locks_reject_before_publication_and_fresh_preview_retries(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading, httpx
from core.assistant_runtime.host import create_app
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.initial_migration_binding import list_initial_intents
async def run():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=2, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                 headers={'Authorization':'Bearer private-test-token'}) as client:
        for lock in (history_host._import_lock, history_host._lock, sessions._RUNNING_SESSIONS_LOCK, native._LOCK):
            token = preview.preview('registered:1', turn_id='turn-one')['previewId']
            op = initial_migration_id('registered:1', token, 'knowledge')
            request = {'projectId':'registered:1', 'previewId':token, 'turnId':'turn-one',
                       'category':'knowledge', 'operationId':op}
            task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
            wire = (await broker.claim())['request']
            acquired, release = threading.Event(), threading.Event()
            def hold():
                with lock:
                    acquired.set()
                    assert release.wait(10)
            thread = threading.Thread(target=hold); thread.start()
            assert await asyncio.to_thread(acquired.wait, 5)
            try:
                duplicate_token = preview.preview('registered:1', turn_id='turn-one')['previewId']
                duplicate = await broker.invoke('initial_migration_queue', {**request, 'previewId':duplicate_token}, turn_id='turn-one')
                assert duplicate['state'] == 'unknown'
                response = await client.post('/api/assistant/initial-migration/prepare',
                    json={**request, 'deliveryId':wire['deliveryId'], 'revision':1})
            finally:
                release.set(); await asyncio.to_thread(thread.join, 5)
            assert response.json() == {'schemaVersion':1, 'operationId':op, 'state':'rejected', 'code':'busy'}
            assert list_initial_intents(target) == []
            result = {'schemaVersion':1, **{k:request[k] for k in ('projectId','previewId','category','operationId')},
                      'state':'rejected', 'code':'busy', 'readyForCutover':False}
            assert broker.settle(wire['deliveryId'], result)
            assert (await task)['code'] == 'busy'
        token = preview.preview('registered:1', turn_id='turn-one')['previewId']
        op = initial_migration_id('registered:1', token, 'knowledge')
        request = {'projectId':'registered:1', 'previewId':token, 'turnId':'turn-one',
                   'category':'knowledge', 'operationId':op}
        task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
        wire = (await broker.claim())['request']
        acquired = threading.Event()
        def brief_contention():
            with history_host._import_lock:
                acquired.set()
                threading.Event().wait(0.12)
        thread = threading.Thread(target=brief_contention); thread.start()
        assert await asyncio.to_thread(acquired.wait, 5)
        response = await client.post('/api/assistant/initial-migration/prepare',
            json={**request, 'deliveryId':wire['deliveryId'], 'revision':1})
        await asyncio.to_thread(thread.join, 5)
        assert response.status_code == 200 and response.json()['operationId'] == op, response.text
        result = {'schemaVersion':1, **{k:request[k] for k in ('projectId','previewId','category','operationId')},
                  'state':'queued', 'code':'queued', 'readyForCutover':False}
        assert broker.settle(wire['deliveryId'], result) and (await task)['state'] == 'queued'
        assert len(list_initial_intents(target)) == 1
    broker.close()
try: asyncio.run(run())
finally: cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_busy_does_not_survive_cancellation_or_publication(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading, httpx
from core.assistant_runtime.host import create_app
from core.assistant_runtime.history_host import InitialPrepareBusy
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
async def run():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=2, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    original = history_host.prepare_initial_source
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                 headers={'Authorization':'Bearer private-test-token'}) as client:
        for mode in ('cancel', 'published'):
            token = preview.preview('registered:1', turn_id='turn-one')['previewId']
            category = 'knowledge' if mode == 'cancel' else 'personal'
            op = initial_migration_id('registered:1', token, category)
            request = {'projectId':'registered:1', 'previewId':token, 'turnId':'turn-one',
                       'category':category, 'operationId':op}
            task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
            wire = (await broker.claim())['request']
            entered, release = threading.Event(), threading.Event()
            def blocked(*args, **kwargs):
                publication = args[6]
                if mode == 'published': publication.publish(lambda: None)
                entered.set()
                assert release.wait(10)
                raise InitialPrepareBusy('initial_migration_busy')
            history_host.prepare_initial_source = blocked
            pending = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
                json={**request, 'deliveryId':wire['deliveryId'], 'revision':1}))
            assert await asyncio.to_thread(entered.wait, 5)
            if mode == 'cancel': broker.begin_initial_fence('turn-one')
            release.set()
            response = await pending
            assert response.status_code == 409
            if mode == 'cancel':
                assert (await task)['state'] == 'unknown'
                broker.end_initial_fence('turn-one')
                duplicate_token = preview.preview('registered:1', turn_id='turn-one')['previewId']
                assert (await broker.invoke('initial_migration_queue', {**request, 'previewId':duplicate_token}, turn_id='turn-one'))['state'] == 'unknown'
            else:
                result = {'schemaVersion':1, **{k:request[k] for k in ('projectId','previewId','category','operationId')},
                          'state':'rejected', 'code':'busy', 'readyForCutover':False}
                try: broker.settle(wire['deliveryId'], result)
                except ValueError: pass
                else: raise AssertionError('publication mislabeled busy')
                found, publication = broker.begin_initial_drain(wire['deliveryId'], op)
                assert found and publication.wait_finished(1) and (await task)['state'] == 'unknown'
    history_host.prepare_initial_source = original
    broker.close()
try: asyncio.run(run())
finally: cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_cancellation_during_real_publication_is_unknown_and_cannot_replay(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, threading, httpx
from core.assistant_runtime.host import create_app
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime import initial_migration_binding as binding
async def run():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=2, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    token = preview.preview('registered:1', turn_id='turn-one')['previewId']
    op = initial_migration_id('registered:1', token, 'knowledge')
    request = {'projectId':'registered:1', 'previewId':token, 'turnId':'turn-one',
               'category':'knowledge', 'operationId':op}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    entered, release = threading.Event(), threading.Event()
    original = binding.publish_initial_intent
    def paused(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(10)
        return result
    binding.publish_initial_intent = paused
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                     headers={'Authorization':'Bearer private-test-token'}) as client:
            pending = asyncio.create_task(client.post('/api/assistant/initial-migration/prepare',
                json={**request, 'deliveryId':wire['deliveryId'], 'revision':1}))
            assert await asyncio.to_thread(entered.wait, 5)
            assert binding.read_initial_intent(target, op)['operationId'] == op
            broker.begin_initial_fence('turn-one')
            assert (await task)['state'] == 'unknown'
            release.set()
            assert (await pending).status_code == 409
            broker.end_initial_fence('turn-one')
            next_token = preview.preview('registered:1', turn_id='turn-one')['previewId']
            assert (await broker.invoke('initial_migration_queue', {**request, 'previewId':next_token}, turn_id='turn-one'))['state'] == 'unknown'
    finally:
        release.set()
        binding.publish_initial_intent = original
        broker.close()
try: asyncio.run(run())
finally: cleanup()
''', config_text=TEST_MODEL_CONFIG)
