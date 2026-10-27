"""Launcher-only reminder protocol against isolated native profiles."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime.host import create_app
from core.assistant_runtime.reminder_receipts import ReminderReceiptError
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
from tests.test_assistant_runtime_host import Native


@pytest.mark.parametrize(('error', 'status'), [
    ('reminder_imported_profile_blocked', 409),
    ('receipt_capacity_exceeded', 409),
    ('receipt_admission_closed', 409),
    ('receipt_store_busy', 503),
    ('receipt_store_unavailable', 503),
    ('unexpected_reminder_failure', 503),
])
def test_reminder_protocol_distinguishes_permanent_and_transient_errors(error, status):
    class Owner:
        def next(self):
            raise ReminderReceiptError(error)

    app = create_app(native=Native(), token='isolated-main-token')
    with ThreadPoolExecutor(max_workers=1) as executor:
        with TestClient(app, base_url='http://127.0.0.1') as client:
            app.state.reminders = Owner()
            app.state.reminder_executor = executor
            response = client.post('/api/assistant/reminders/next',
                                   headers={'Authorization': 'Bearer isolated-main-token'})
            assert response.status_code == status
            assert response.json()['detail']['code'] == error


def test_native_due_reminder_persists_across_restart_and_blocks_imported_profile(tmp_path):
    _run(tmp_path, r'''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import personal_affairs_service
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
headers = {'Authorization': 'Bearer isolated-main-token'}
app = create_app(native=NativeFacade(root), token='isolated-main-token')
with TestClient(app, base_url='http://127.0.0.1') as client:
    path = '/api/assistant/reminders/next'
    assert client.post(path).status_code == 401
    assert client.post(path, headers={**headers, 'Origin': 'http://localhost'}).status_code == 403
    assert client.get(path, headers=headers).status_code == 405
    assert client.post(path, headers=headers).json()['event'] is None
    agent = app.state.assistant['assistant']['agentId']
    personal_affairs_service.get_personal_affairs_service().add_item(
        agent, kind='todo', title='fixture due', due_at='2020-01-01T00:00:00Z')
    response = client.post(path, headers=headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    event = response.json()['event']
    assert event['kind'] == 'affair_reminder' and event['title'] == '事务提醒：fixture due'
    assert event['targetUrl'] == ''
    assert event['recoveredFallback'] is False
    assert client.post(path, headers=headers).json()['event'] is None
    body = {'eventId': event['id'], 'attemptToken': event['attemptToken'], 'channel': 'system_notification'}
    fallback = {key: body[key] for key in ('eventId', 'attemptToken')}
    pending = client.post('/api/assistant/reminders/fallback', headers=headers, json=fallback)
    assert pending.status_code == 503 and pending.json()['detail']['code'] == 'receipt_fallback_not_allowed'
    receipt = client.post('/api/assistant/reminders/submitted', headers=headers, json=body).json()['receipt']
    assert receipt['state'] == 'submitted' and not receipt['interactionObserved']
    (root / 'fixture-event.json').write_text(json.dumps(body))
''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, r'''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
headers = {'Authorization': 'Bearer isolated-main-token'}
body = json.loads((root / 'fixture-event.json').read_text())
with TestClient(create_app(native=NativeFacade(root), token='isolated-main-token'),
                base_url='http://127.0.0.1') as client:
    assert client.post('/api/assistant/reminders/next', headers=headers).json()['event'] is None
    fallback = {key: body[key] for key in ('eventId', 'attemptToken')}
    assert client.post('/api/assistant/reminders/fallback', json=fallback).status_code == 401
    bad = client.post('/api/assistant/reminders/fallback', headers=headers,
                      json={**fallback, 'attemptToken': '0' * 64})
    assert bad.status_code == 503 and bad.json()['detail']['code'] == 'receipt_attempt_owner_required'
    result = client.post('/api/assistant/reminders/fallback', headers=headers, json=fallback)
    assert result.status_code == 200
    assert result.json()['receipt']['state'] == 'submitted'
    assert result.json()['receipt']['channel'] == 'attention_fallback'
    assert not result.json()['receipt']['interactionObserved']
    body['channel'] = 'attention_fallback'
    opened = client.post('/api/assistant/reminders/opened', headers=headers, json=body)
    assert opened.status_code == 200 and opened.json()['receipt']['interactionObserved']
    assert client.post('/api/assistant/reminders/fallback', headers=headers, json=fallback).status_code == 503
    (root / 'affairs_migrations').mkdir()
    result = client.post('/api/assistant/reminders/next', headers=headers)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'reminder_imported_profile_blocked'
''', config_text=TEST_MODEL_CONFIG)


def test_cross_day_keeps_inflight_owner_then_reopens_for_click(tmp_path):
    _run(tmp_path, r'''
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime import reminders
from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import personal_affairs_service
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
class Clock:
    day = 1
    @classmethod
    def now(cls, tz): return datetime(2026, 10, cls.day, tzinfo=timezone.utc)
reminders.datetime = Clock
headers = {'Authorization': 'Bearer isolated-main-token'}
app = create_app(native=NativeFacade(root), token='isolated-main-token')
with TestClient(app, base_url='http://127.0.0.1') as client:
    agent = app.state.assistant['assistant']['agentId']
    personal_affairs_service.get_personal_affairs_service().add_item(
        agent, kind='todo', title='fixture', due_at='2020-01-01T00:00:00Z')
    event = client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    Clock.day = 2
    assert client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    assert '20261001' in app.state.reminders.stores
    body = {'eventId': event['id'], 'attemptToken': event['attemptToken'], 'channel': 'system_notification'}
    assert client.post('/api/assistant/reminders/submitted', headers=headers, json=body).status_code == 200
    assert '20261001' not in app.state.reminders.stores
    assert client.post('/api/assistant/reminders/opened', headers=headers, json=body).json()['receipt']['interactionObserved']
    assert '20261001' not in app.state.reminders.stores
''', config_text=TEST_MODEL_CONFIG)


def test_queued_fallback_recovers_after_restart_until_user_interacts(tmp_path):
    _run(tmp_path, r'''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import personal_affairs_service
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
headers = {'Authorization': 'Bearer isolated-main-token'}
app = create_app(native=NativeFacade(root), token='isolated-main-token')
with TestClient(app, base_url='http://127.0.0.1') as client:
    agent = app.state.assistant['assistant']['agentId']
    personal_affairs_service.get_personal_affairs_service().add_item(
        agent, kind='todo', title='queued fallback', due_at='2020-01-01T00:00:00Z')
    event = client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    assert event['recoveredFallback'] is False
    body = {'eventId': event['id'], 'attemptToken': event['attemptToken'], 'channel': 'attention_fallback'}
    assert client.post('/api/assistant/reminders/submitted', headers=headers, json=body).status_code == 200
    assert client.post('/api/assistant/reminders/next', headers=headers).json()['event'] is None
    (root / 'queued-event.json').write_text(json.dumps(body))
''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, r'''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
headers = {'Authorization': 'Bearer isolated-main-token'}
old = json.loads((root / 'queued-event.json').read_text())
with TestClient(create_app(native=NativeFacade(root), token='isolated-main-token'),
                base_url='http://127.0.0.1') as client:
    event = client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    assert event['id'] == old['eventId'] and event['recoveredFallback'] is True
    assert event['attemptToken'] != old['attemptToken']
    assert client.post('/api/assistant/reminders/next', headers=headers).json()['event'] is None
    assert client.post('/api/assistant/reminders/opened', headers=headers, json=old).status_code != 200
    (root / 'recovered-event.json').write_text(json.dumps(event))
''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, r'''
import json, os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
headers = {'Authorization': 'Bearer isolated-main-token'}
prior = json.loads((root / 'recovered-event.json').read_text())
with TestClient(create_app(native=NativeFacade(root), token='isolated-main-token'),
                base_url='http://127.0.0.1') as client:
    event = client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    assert event['id'] == prior['id'] and event['recoveredFallback'] is True
    assert event['attemptToken'] != prior['attemptToken']
    body = {'eventId': event['id'], 'attemptToken': event['attemptToken'], 'channel': 'attention_fallback'}
    assert client.post('/api/assistant/reminders/submitted', headers=headers, json=body).status_code == 200
    opened = client.post('/api/assistant/reminders/opened', headers=headers, json=body)
    assert opened.status_code == 200 and opened.json()['receipt']['interactionObserved']
import apsw
day = event['id'].split(':')[1]
db = apsw.Connection(str(root / 'reminder_receipts' / day / 'reminders.sqlite3'))
try:
    assert list(db.execute('SELECT count(*) FROM receipt_inflight')) == [(0,)]
    assert list(db.execute('SELECT count(*) FROM receipt_senders')) == [(0,)]
finally:
    db.close()
''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, r'''
import os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime.host import NativeFacade, create_app
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
with TestClient(create_app(native=NativeFacade(root), token='isolated-main-token'),
                base_url='http://127.0.0.1') as client:
    result = client.post('/api/assistant/reminders/next', headers={'Authorization': 'Bearer isolated-main-token'})
    assert result.json()['event'] is None
''', config_text=TEST_MODEL_CONFIG)


def test_daily_capacity_is_visible_and_never_resubmits(tmp_path):
    _run(tmp_path, r'''
import os
from pathlib import Path
from fastapi.testclient import TestClient
from core.assistant_runtime import reminders
from core.assistant_runtime.host import NativeFacade, create_app
from core.web.services import personal_affairs_service
root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
reminders._DAILY_CAPACITY = 1
headers = {'Authorization': 'Bearer isolated-main-token'}
app = create_app(native=NativeFacade(root), token='isolated-main-token')
with TestClient(app, base_url='http://127.0.0.1') as client:
    agent = app.state.assistant['assistant']['agentId']
    service = personal_affairs_service.get_personal_affairs_service()
    for title in ('first', 'second'):
        service.add_item(agent, kind='todo', title=title, due_at='2020-01-01T00:00:00Z')
    assert client.post('/api/assistant/reminders/next', headers=headers).json()['event']
    result = client.post('/api/assistant/reminders/next', headers=headers)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'receipt_capacity_exceeded'
''', config_text=TEST_MODEL_CONFIG)
