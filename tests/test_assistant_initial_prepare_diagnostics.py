"""Initial admission diagnostics must not leak request or exception contents."""
from core.assistant_runtime.host import _initial_prepare_failure_code
from core.assistant_runtime.migration_io import MigrationIOError
from tests.test_assistant_online_affairs_host import _HOST_SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_prepare_failure_classification_is_closed():
    assert _initial_prepare_failure_code(MigrationIOError('initial_migration_busy')) == 'initial_migration_busy'
    assert _initial_prepare_failure_code(MigrationIOError('C:/PRIVATE/path SECRET')) == 'migration_error'
    assert _initial_prepare_failure_code(ValueError('C:/PRIVATE/path SECRET')) == 'value_error'
    assert _initial_prepare_failure_code(PermissionError('C:/PRIVATE/path SECRET')) == 'permission_error'


def test_private_prepare_logs_phase_without_exception_or_request_data(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, logging, httpx
from core.assistant_runtime.main_control import MainControlBroker, initial_migration_id
from core.assistant_runtime.host import create_app
from core.assistant_runtime.migration_io import MigrationIOError
class Capture(logging.Handler):
    def emit(self, record): lines.append(record.getMessage())
lines = []
handler = Capture()
logger = logging.getLogger('core.assistant_runtime.host')
logger.addHandler(handler)
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, claim_seconds=1, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    request = {'projectId': 'registered:1', 'previewId': value['previewId'], 'turnId': 'turn-one',
               'category': 'knowledge', 'operationId': initial_migration_id('registered:1', value['previewId'], 'knowledge')}
    task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn-one'))
    wire = (await broker.claim())['request']
    def failure(*args): raise MigrationIOError('C:/PRIVATE/path SECRET')
    history_host.prepare_initial_source = failure
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                     headers={'Authorization': 'Bearer private-test-token'}) as client:
            response = await client.post('/api/assistant/initial-migration/prepare',
                json={**request, 'revision': 1, 'deliveryId': wire['deliveryId']})
            assert response.status_code == 409
        assert lines == ['assistant_initial_prepare category=knowledge phase=prepare code=migration_error']
        assert 'PRIVATE' not in str(lines) and 'SECRET' not in str(lines) and value['previewId'] not in str(lines)
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        broker.close()
try:
    asyncio.run(run_case())
finally:
    logger.removeHandler(handler)
    cleanup()
''', config_text=TEST_MODEL_CONFIG)
