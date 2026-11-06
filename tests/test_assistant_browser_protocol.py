import asyncio
import json
from copy import deepcopy

import pytest

from core.assistant_runtime import browser_protocol as browser
from core.assistant_runtime.actions import bind_actions, unbind_actions, execute_action, browser_interact_approval_summary
from core.assistant_runtime.main_control import MainControlBroker
from tests.test_assistant_runtime_actions import Dispatch

PAGE = '8e2731f7-06a2-41db-bfa2-cbe76a099811'
SNAP = '8e2731f7-06a2-41db-bfa2-cbe76a099812'
RUNTIME = {'agentId': 'test-agent', 'sessionId': 'test-session', 'turnId': 'test-turn'}
STATE = {'pages': [{'id': PAGE, 'url': 'https://example.org/', 'title': 'Example', 'loading': False,
                    'canGoBack': False, 'canGoForward': False}], 'activePageId': PAGE, 'takeover': False}
SNAPSHOT = {'pageId': PAGE, 'snapshotId': SNAP, 'url': 'https://example.org/', 'title': 'Example',
            'untrusted': True, 'text': 'Untrusted text', 'elements': [{'ref': '1', 'role': 'button', 'name': 'Submit'}]}
ARGS = {'page_id': PAGE, 'snapshot_id': SNAP, 'element_ref': '1', 'url': 'https://example.org/',
        'element_name': 'Submit', 'operation': 'click'}
REQ = {'pageId': PAGE, 'snapshotId': SNAP, 'elementRef': '1', 'url': 'https://example.org/',
       'elementName': 'Submit', 'operation': 'click'}


def result(action, **extra):
    return {'schemaVersion': 1, 'operation': action, 'code': 'ok', **extra}


@pytest.mark.parametrize(('action', 'arguments'), [
    ('browser_ensure', {'url': 'https://example.org/path?q=one#part'}),
    ('browser_select', {'pageId': PAGE}), ('browser_show', {}),
])
def test_reuse_requests_and_results_remain_closed(action, arguments):
    request = arguments
    assert browser.validate_request(action, request) == request
    assert browser.validate_result(action, request, result(action[8:], state=STATE))['state'] == STATE
    for extra in ({'approved': True}, {'source': 'operator'}, {'operation': 'resume'}, {'value': 'private'}):
        with pytest.raises(ValueError): browser.validate_request(action, {**request, **extra})
    for bad_state in ({**STATE, 'visible': True}, {**STATE, 'pages': [{**STATE['pages'][0], 'selected': True}]}):
        with pytest.raises(ValueError): browser.validate_result(action, request, result(action[8:], state=bad_state))
    with pytest.raises(ValueError): browser.validate_result(action, request, {**result(action[8:], state=STATE), 'approved': True})


def test_reuse_actions_reject_missing_or_unsafe_targets_and_control_transfer():
    for action, request in [('browser_ensure', {}), ('browser_ensure', {'url': 'https://user:pass@example.org/'}),
                            ('browser_ensure', {'url': 'javascript:alert(1)'}), ('browser_select', {}),
                            ('browser_select', {'pageId': 'invalid'}), ('browser_show', {'pageId': PAGE}),
                            ('browser_resume', {}), ('browser_takeover', {})]:
        with pytest.raises(ValueError): browser.validate_request(action, request)


def test_native_reuse_actions_publish_closed_schemas_and_dispatch_exact_targets():
    async def run():
        broker = MainControlBroker(lambda: (), browser_enabled=True)
        dispatch = Dispatch()
        bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
        try:
            for action, args, request in [
                ('browser_ensure', {'url': 'https://example.org/path?q=one#part'}, {'url': 'https://example.org/path?q=one#part'}),
                ('browser_select', {'page_id': PAGE}, {'pageId': PAGE}), ('browser_show', {}, {}),
            ]:
                contract = await asyncio.to_thread(execute_action, 'describe', {'action': action})
                assert contract['governed'] is False and contract['parameters']['additionalProperties'] is False
                assert set(contract['parameters'].get('required', [])) == set(args)
                with pytest.raises(ValueError): await asyncio.to_thread(execute_action, action, args)
                with pytest.raises(ValueError): await asyncio.to_thread(execute_action, action, {**args, 'approved': True}, runtime=RUNTIME)
                flight = asyncio.create_task(asyncio.to_thread(execute_action, action, args, runtime=RUNTIME))
                claimed = (await broker.claim())['request']
                assert {k: v for k, v in claimed.items() if k not in {'action', 'deliveryId'}} == request
                assert broker.settle(claimed['deliveryId'], result(action[8:], state=STATE))
                assert await flight == {**result(action[8:], state=STATE), 'source': 'launcher-browser', 'untrustedContent': True}
        finally:
            broker.close(); unbind_actions(dispatch)
    asyncio.run(run())


def test_closed_requests_reject_unapproved_capabilities_and_bad_values():
    assert browser.validate_request('browser_interact', REQ) == REQ
    for request in ({**REQ, 'selector': '#secret'}, {**REQ, 'operation': 'click', 'value': ''},
                    {**REQ, 'operation': 'fill'}, {**REQ, 'operation': 'fill', 'value': 'x' * 2001},
                    {**REQ, 'elementRef': '0'}, {**REQ, 'pageId': 'bad'}):
        with pytest.raises(ValueError): browser.validate_request('browser_interact', request)
    for url in ('file:///tmp/x', 'https://user:pass@example.org/', 'javascript:alert(1)'):
        with pytest.raises(ValueError): browser.validate_request('browser_open', {'url': url})
    with pytest.raises(ValueError): browser.validate_request('browser_scroll', {'pageId': PAGE, 'direction': 'left'})


def test_closed_results_enforce_identity_untrusted_and_bounds():
    req = {'pageId': PAGE}
    valid = result('read', snapshot=SNAPSHOT)
    assert browser.validate_result('browser_read', req, valid) == valid
    variants = [
        {**SNAPSHOT, 'pageId': SNAP}, {**SNAPSHOT, 'untrusted': False},
        {**SNAPSHOT, 'url': 'https://user@example.org/'}, {**SNAPSHOT, 'text': 'x' * 8001},
        {**SNAPSHOT, 'elements': SNAPSHOT['elements'] * 2},
        {**SNAPSHOT, 'elements': [{'ref': '1', 'name': 'x', 'role': 'button', 'selector': '#x'}]},
        {**SNAPSHOT, 'title': 'x', 'unexpected': 'private'},
    ]
    for snapshot in variants:
        with pytest.raises(ValueError): browser.validate_result('browser_read', req, result('read', snapshot=snapshot))
    assert browser.validate_result('browser_open', {'url': 'https://example.org/'}, result('open', state=STATE))
    for bad in ({**STATE, 'activePageId': SNAP}, {**STATE, 'pages': STATE['pages'] * 5}, {**STATE, 'takeover': 1}):
        with pytest.raises(ValueError): browser.validate_result('browser_open', {'url': 'https://example.org/'}, result('open', state=bad))
    for code in browser.ERROR_CODES:
        assert browser.validate_result('browser_read', req, {'schemaVersion': 1, 'operation': 'read', 'code': code})['code'] == code
    for bad in ({'schemaVersion': 1, 'operation': 'read', 'code': 'arbitrary'},
                {'schemaVersion': 1, 'operation': 'read', 'code': 'BROWSER_ACTION_FAILED', 'message': 'private'}):
        with pytest.raises(ValueError): browser.validate_result('browser_read', req, bad)


def test_approval_summary_preserves_exact_reviewed_values_and_rejects_forgery():
    assert browser_interact_approval_summary(ARGS) == {'assistantAction': 'browser_interact', 'assistantTargets': ARGS,
                                                      'assistantOperationDescription': '点击网页上的所选元素。'}
    fill = {**ARGS, 'operation': 'fill', 'value': '  exact\ntext  '}
    assert browser_interact_approval_summary(fill)['assistantTargets'] == fill
    for args in ({**ARGS, 'value': ''}, {**ARGS, 'selector': '#x'}, {**ARGS, 'element_ref': '0'},
                 {**ARGS, 'url': 'https://user@example.org/'}, {**fill, 'value': None}):
        with pytest.raises(ValueError): browser_interact_approval_summary(args)


def test_broker_explicit_capability_result_validation_and_timeout():
    async def run():
        disabled = MainControlBroker(lambda: ())
        with pytest.raises(ValueError): await disabled.invoke('browser_state', {})
        broker = MainControlBroker(lambda: (), browser_enabled=True, timeout_seconds=.05)
        pending = asyncio.create_task(broker.invoke('browser_read', {'pageId': PAGE}))
        claim = (await broker.claim())['request']
        assert claim['action'] == 'browser_read' and claim['pageId'] == PAGE
        with pytest.raises(ValueError): broker.settle(claim['deliveryId'], result('read', snapshot={**SNAPSHOT, 'pageId': SNAP}))
        assert broker.settle(claim['deliveryId'], result('read', snapshot=SNAPSHOT))
        assert (await pending)['snapshot'] == SNAPSHOT
        assert (await broker.invoke('browser_state', {})) == {'schemaVersion': 1, 'operation': 'state', 'code': 'BROWSER_UNAVAILABLE'}
        broker.close(); disabled.close()
    asyncio.run(run())


def test_claimed_browser_timeout_and_close_are_unknown_without_replay():
    async def run():
        for close in (False, True):
            broker = MainControlBroker(lambda: (), browser_enabled=True, timeout_seconds=.05)
            pending = asyncio.create_task(broker.invoke('browser_interact', REQ))
            claimed = (await broker.claim())['request']
            if close:
                broker.close()
            output = await pending
            assert output == {'schemaVersion': 1, 'operation': 'interact', 'code': 'BROWSER_ACTION_OUTCOME_UNKNOWN'}
            assert not broker.settle(claimed['deliveryId'], result('interact', state=STATE))
            assert broker._queue.empty()
            broker.close()
    asyncio.run(run())


def test_native_identity_governance_and_camel_case_request():
    async def run():
        broker = MainControlBroker(lambda: (), browser_enabled=True)
        dispatch = Dispatch()
        bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
        try:
            contract = await asyncio.to_thread(execute_action, 'describe', {'action': 'browser_interact'})
            assert contract['governed'] is True and contract['parameters']['additionalProperties'] is False
            assert (await asyncio.to_thread(execute_action, 'browser_interact', ARGS, runtime=RUNTIME))['status'] == 'approval_required'
            with pytest.raises(ValueError): await asyncio.to_thread(execute_action, 'browser_interact', ARGS, governed=True)
            with pytest.raises(ValueError): await asyncio.to_thread(execute_action, 'browser_interact', {**ARGS, 'selector': 'x'}, runtime=RUNTIME, governed=True)
            flight = asyncio.create_task(asyncio.to_thread(execute_action, 'browser_interact', ARGS, runtime=RUNTIME, governed=True))
            claim = (await broker.claim())['request']
            assert {k: v for k, v in claim.items() if k not in {'action', 'deliveryId'}} == REQ
            assert broker.settle(claim['deliveryId'], result('interact', state=STATE))
            output = await flight
            assert output == {**result('interact', state=STATE), 'source': 'launcher-browser', 'untrustedContent': True}
        finally:
            broker.close(); unbind_actions(dispatch)
    asyncio.run(run())


def test_browser_actions_require_canonical_identity_before_dispatch(monkeypatch):
    from tools import personal_assistant_tools as tools
    from core.web.services import agent_directory_service as directory
    monkeypatch.setattr(directory, 'current_agent_runtime', lambda: {'agentId': 'fake', 'sessionId': 'fake'})
    monkeypatch.setattr(directory, 'get_agent', lambda _: None)
    result = json.loads(tools.personal_assistant_action_tool('browser_state', {}))
    assert result['status'] == 'blocked'
    result = json.loads(tools.personal_assistant_manage_tool('browser_interact', json.dumps(ARGS)))
    assert result['status'] == 'blocked'


def test_transport_limit_and_health_only_expand_when_capability_enabled():
    from fastapi.testclient import TestClient
    from core.assistant_runtime.host import create_app
    class Native:
        def bootstrap(self): return {'assistant': {'agentId': 'synthetic', 'directSessionId': 'synthetic'}}
        def shutdown(self): pass
    class Control:
        def __init__(self, enabled): self.browser_enabled = enabled
        def close(self): pass
        def settle(self, delivery, value): return True
    token = 'synthetic-token-for-browser-test'
    payload = {'schemaVersion': 1, 'deliveryId': 'a' * 32, 'result': {'padding': 'x' * 5000}}
    for enabled in (False, True):
        with TestClient(create_app(native=Native(), token=token, main_control=Control(enabled)),
                        base_url='http://127.0.0.1', headers={'Authorization': 'Bearer ' + token}) as client:
            assert ('browserControlVersion' in client.get('/health').json()) is enabled
            assert client.post('/api/assistant/main-control/settle', json=payload).status_code == (200 if enabled else 413)
            assert client.post('/api/assistant/main-control/settle', content=b'x' * (128 * 1024 + 1)).status_code == 413


def test_long_browser_result_remains_complete_for_model_with_exact_refs():
    from core.assistant_runtime.actions import _browser_model_result
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    elements = [{'ref': str(i + 1), 'role': 'button' if i >= 40 else 'generic',
                 'name': ('按钮 English ' * 15)[:160]} for i in range(80)]
    snapshot = {**SNAPSHOT, 'text': '内容 English ' * 700, 'elements': elements}
    model = _browser_model_result(result('read', snapshot=snapshot))
    raw, outcome, facts, rendered = _through_native_model_budget(model)
    assert model['truncated'] is True and len(raw) <= 3400
    assert not facts.truncated and outcome is None
    assert json.loads(rendered.split('\nResult:\n', 1)[1]) == json.loads(raw)
    assert model['snapshot']['snapshotId'] == SNAP
    assert model['snapshot']['elements'][0]['ref'] == '41'
    assert all(row in elements for row in model['snapshot']['elements'])
    assert snapshot['text'].startswith(model['snapshot']['text'])
    assert snapshot['text'] == '内容 English ' * 700


def test_long_tab_state_returns_error_instead_of_dropping_page_bindings():
    from core.assistant_runtime.actions import _browser_model_result
    pages = [{**STATE['pages'][0], 'id': f'8e2731f7-06a2-41db-bfa2-cbe76a09981{i}',
              'url': 'https://example.org/' + 'x' * 1900} for i in range(4)]
    state = {'pages': pages, 'activePageId': pages[2]['id'], 'takeover': False}
    model = _browser_model_result(result('state', state=state))
    assert model['code'] == 'BROWSER_UNAVAILABLE' and 'state' not in model
    assert len(json.dumps(model, ensure_ascii=False)) <= 3400
    after_navigation = _browser_model_result(result('navigate', state=state))
    assert after_navigation['code'] == 'BROWSER_ACTION_OUTCOME_UNKNOWN' and 'state' not in after_navigation


def test_full_url_contract_preserves_query_fragment_and_utf16_limit():
    from core.assistant_runtime.actions import BrowserInteract, _browser_model_result
    base = 'https://example.org/path?key=value&next=%2F#section'
    assert BrowserInteract.model_json_schema()['properties']['url']['maxLength'] == 8192
    assert _browser_model_result(result('read', snapshot={**SNAPSHOT, 'url': base}))['snapshot']['url'] == base
    url = base + '😀' * ((8192 - len(base)) // 2) + 'x' * ((8192 - len(base)) % 2)
    assert browser.validate_request('browser_open', {'url': url}) == {'url': url}
    assert browser.validate_request('browser_interact', {**REQ, 'url': url})['url'] == url
    assert browser_interact_approval_summary({**ARGS, 'url': url})['assistantTargets']['url'] == url
    state = {**STATE, 'pages': [{**STATE['pages'][0], 'url': url}]}
    assert browser.validate_result('browser_state', {}, result('state', state=state))['state'] == state
    snapshot = {**SNAPSHOT, 'url': url}
    assert browser.validate_result('browser_read', {'pageId': PAGE}, result('read', snapshot=snapshot))['snapshot'] == snapshot
    for invalid in (url + 'x', 'https://user:pass@example.org/?x=1#frag',
                    'https://example.org/?x=1\n#frag', 'https://example.org/\x7f'):
        for action, request in (('browser_open', {'url': invalid}), ('browser_interact', {**REQ, 'url': invalid})):
            with pytest.raises(ValueError): browser.validate_request(action, request)
        with pytest.raises(ValueError):
            browser.validate_result('browser_read', {'pageId': PAGE}, result('read', snapshot={**SNAPSHOT, 'url': invalid}))
        with pytest.raises(ValueError):
            browser.validate_result('browser_state', {}, result('state', state={**STATE, 'pages': [{**STATE['pages'][0], 'url': invalid}]}))
    with pytest.raises(ValueError): browser_interact_approval_summary({**ARGS, 'url': url + 'x'})


def test_oversized_essential_urls_return_bounded_json_error():
    from core.assistant_runtime.actions import _browser_model_result
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    url = 'https://example.org/?query=' + 'x' * 5000 + '#fragment'
    values = [result('read', snapshot={**SNAPSHOT, 'url': url}),
              result('interact', state={**STATE, 'pages': [{**STATE['pages'][0], 'url': url}]})]
    for value in values:
        model = _browser_model_result(value)
        raw, _, facts, rendered = _through_native_model_budget(model)
        expected = 'BROWSER_UNAVAILABLE' if value['operation'] == 'read' else 'BROWSER_ACTION_OUTCOME_UNKNOWN'
        assert model['code'] == expected and model['operation'] == value['operation']
        assert 'snapshot' not in model and 'state' not in model
        assert len(raw) <= 3400 and not facts.truncated
        assert json.loads(rendered.split('\nResult:\n', 1)[1]) == json.loads(raw)


def test_pathological_titles_still_fit_and_keep_exact_active_target():
    from core.assistant_runtime.actions import _browser_model_result
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    url = 'https://example.org/' + 'x' * 2000
    snapshot = {**SNAPSHOT, 'url': url, 'title': '\u0001' * 200, 'text': 'x' * 8000}
    output = _browser_model_result(result('read', snapshot=snapshot))
    raw, _, facts, rendered = _through_native_model_budget(output)
    assert len(raw) <= 3400 and not facts.truncated and json.loads(rendered.split('\nResult:\n', 1)[1])['snapshot']['url'] == url
    state = {**STATE, 'pages': [{**STATE['pages'][0], 'url': url, 'title': '\u0001' * 200}]}
    output = _browser_model_result(result('state', state=state))
    assert output['state']['pages'][0]['id'] == PAGE and output['state']['pages'][0]['url'] == url
    assert len(json.dumps(output, ensure_ascii=False)) <= 3400


def test_unknown_after_submission_is_forwarded_as_failure_without_replay():
    async def run():
        broker = MainControlBroker(lambda: (), browser_enabled=True)
        dispatch = Dispatch()
        bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
        try:
            flight = asyncio.create_task(asyncio.to_thread(execute_action, 'browser_interact', ARGS, runtime=RUNTIME, governed=True))
            claim = (await broker.claim())['request']
            failure = {'schemaVersion': 1, 'operation': 'interact', 'code': 'BROWSER_ACTION_OUTCOME_UNKNOWN'}
            assert broker.settle(claim['deliveryId'], failure)
            output = await flight
            assert output == {**failure, 'source': 'launcher-browser', 'untrustedContent': True}
            assert 'state' not in output and 'ok' not in output
            with pytest.raises(ValueError):
                browser.validate_result('browser_interact', REQ, {**failure, 'state': STATE})
            assert broker._queue.empty()
        finally:
            broker.close(); unbind_actions(dispatch)
    asyncio.run(run())


def test_utf16_browser_fields_and_unicode_fill_boundaries_match_electron():
    good = {**REQ, 'elementName': '😀' * 80}
    assert browser.validate_request('browser_interact', good) == good
    with pytest.raises(ValueError):
        browser.validate_request('browser_interact', {**REQ, 'elementName': '😀' * 81})
    fill = {**REQ, 'operation': 'fill', 'value': '😀' * 2000}
    assert browser.validate_request('browser_interact', fill) == fill
    with pytest.raises(ValueError):
        browser.validate_request('browser_interact', {**fill, 'value': '😀' * 2001})
    snap = {**SNAPSHOT, 'text': '😀' * 4000}
    assert browser.validate_result('browser_read', {'pageId': PAGE}, result('read', snapshot=snap))
    with pytest.raises(ValueError):
        browser.validate_result('browser_read', {'pageId': PAGE}, result('read', snapshot={**snap, 'text': '😀' * 4001}))
    with pytest.raises(ValueError):
        browser.validate_request('browser_open', {'url': 'https://example.org/' + '😀' * 4100})


def test_page_load_error_is_optional_strict_bool_and_state_remains_closed():
    request = {'url': 'https://example.org/'}
    for error in (None, False, True):
        page = dict(STATE['pages'][0])
        if error is not None:
            page['loadError'] = error
        state = {**STATE, 'pages': [page]}
        assert browser.validate_result('browser_open', request, result('open', state=state))['state'] == state
    for extra in ({'loadError': 0}, {'loadError': 'false'}, {'loadError': None}, {'other': True}):
        state = {**STATE, 'pages': [{**STATE['pages'][0], **extra}]}
        with pytest.raises(ValueError):
            browser.validate_result('browser_open', request, result('open', state=state))
