import pytest

from core.assistant_runtime import actions, local_actions, native
from core.web.services import virtual_human_life_service as dialogue


@pytest.fixture
def current(monkeypatch):
    monkeypatch.setattr(native, '_STARTED', True)
    monkeypatch.setattr(native, '_OFFLINE_MIGRATION', False)
    monkeypatch.setattr(native, '_STOP_REQUESTED', __import__('threading').Event())
    monkeypatch.setattr(native, '_AGENT_ID', 'assistant')
    monkeypatch.setattr(native, '_SESSION_ID', 'session')
    return {'agentId': 'assistant', 'sessionId': 'session'}


def test_actions_are_discoverable_and_strict(monkeypatch, current):
    monkeypatch.setattr(actions, '_binding', (object(), object(), None))
    for name in ('preference_proposals', 'preference_proposal_accept', 'preference_proposal_reject', 'dispatch_list'):
        assert [v['action'] for v in actions.execute_action('index', {'query': name})['actions']] == [name]
        contract = actions.execute_action('describe', {'action': name})
        assert contract['parameters']['additionalProperties'] is False
        assert contract['governed'] == ('proposal_accept' in name or 'proposal_reject' in name)
        with pytest.raises(ValueError):
            actions.execute_action(name, {'agent_id': 'foreign'}, runtime=current, governed=True)


def test_proposals_scoped_bounded_and_decisions_require_approval(monkeypatch, current):
    calls = []
    row = {'proposalId': 'p1', 'agentId': 'assistant', 'preferenceType': 'address', 'candidateValue': 'A' * 40,
           'status': 'pending', 'sourceTurnId': 't1', 'createdAt': 'today', 'secret': 'do not return'}
    monkeypatch.setattr(dialogue, 'virtual_human_preference_proposals', lambda agent_id, **kwargs: calls.append((agent_id, kwargs)) or {'proposals': [row] * 30})
    monkeypatch.setattr(dialogue, 'accept_virtual_human_preference_proposal', lambda agent_id, **kwargs: calls.append((agent_id, kwargs)) or {'proposal': row, 'receipt': {'secret': 'no'}})
    result = local_actions.execute('preference_proposals', {'limit': 2}, current)
    assert len(result['proposals']) == 2 and result['untrustedContent'] is True
    assert 'secret' not in str(result) and calls == [('assistant', {'status': ''})]
    fingerprint = result['proposals'][0]['fingerprint']
    decision = {'proposal_id': 'p1', 'expected_fingerprint': fingerprint}
    assert local_actions.execute('preference_proposal_accept', decision, current)['status'] == 'approval_required'
    assert len(calls) == 1
    result = local_actions.execute('preference_proposal_accept', decision, current, governed=True)
    assert calls[-1] == ('assistant', decision) and 'secret' not in str(result)
    for bad in ({'limit': 21}, {'limit': True}, {'status': 'bogus'}, {'agent_id': 'other'}):
        with pytest.raises(ValueError): local_actions.execute('preference_proposals', bad, current)
    with pytest.raises(ValueError): local_actions.execute('preference_proposal_reject', {'proposal_id': 'x' * 161}, current, governed=True)
    with pytest.raises(ValueError): local_actions.execute('preference_proposals', {}, {**current, 'agentId': 'other'})


def test_dispatch_discovery_returns_only_bounded_references(monkeypatch, current):
    class Service:
        def list_dispatches(self, project_id=None):
            assert project_id is None
            return [{'dispatchId': f'd{i}', 'projectId': 'p', 'nativeTaskId': 't', 'receipt': {'status': 'running', 'resultSummary': 'private'}, 'task': 'secret', 'createdAt': 'now'} for i in range(30)]
    monkeypatch.setattr(actions, '_binding', (Service(), object(), None))
    result = actions.execute_action('dispatch_list', {'limit': 2, 'offset': 1}, runtime=current)
    assert [row['dispatchId'] for row in result['dispatches']] == ['d1', 'd2']
    assert result['nextOffset'] == 3 and 'private' not in str(result) and 'secret' not in str(result)
    for bad in ({'limit': 21}, {'offset': -1}, {'project_id': 'p'}, {'limit': True}):
        with pytest.raises(ValueError): actions.execute_action('dispatch_list', bad, runtime=current)
    with pytest.raises(ValueError): actions.execute_action('dispatch_list', {}, runtime={**current, 'sessionId': 'other'})


def test_native_preference_state_machine_remains_authority(tmp_path, monkeypatch, current):
    from datetime import datetime, timezone
    from tests.test_virtual_human_life_preferences import _proposal_service
    monkeypatch.setattr(native, '_AGENT_ID', 'agent-a')
    current['agentId'] = 'agent-a'
    writes = []
    service = _proposal_service(tmp_path, clock=[datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)], writer_calls=writes)
    monkeypatch.setattr(dialogue, 'get_virtual_human_life_service', lambda: service)
    service.queue_conversation_message('agent-a', session_id='session-agent-a', client_submission_id='submission-1', content='短一点')
    proposal = service.propose_companion_preference('agent-a', session_id='session-agent-a', turn_id='turn-user-1', preference_type='verbosity', candidate_value='brief')['proposal']
    proposal_id = proposal['proposalId']
    listed = local_actions.execute('preference_proposals', {}, current)['proposals'][0]
    assert listed['proposalId'] == proposal_id
    decision = {'proposal_id': proposal_id, 'expected_fingerprint': listed['fingerprint']}
    assert not writes
    accepted = local_actions.execute('preference_proposal_accept', decision, current, governed=True)
    assert accepted['proposal']['status'] == 'accepted' and len(writes) == 1
    with pytest.raises(ValueError, match='偏好建议操作结果未确认'):
        local_actions.execute('preference_proposal_reject', decision, current, governed=True)
    assert len(writes) == 1


def test_rejection_and_native_failure_do_not_expose_error(monkeypatch, current):
    calls = []
    row = {'proposalId': 'p1', 'agentId': 'assistant', 'preferenceType': 'humor',
           'candidateValue': 'off', 'status': 'rejected'}
    monkeypatch.setattr(dialogue, 'reject_virtual_human_preference_proposal', lambda agent_id, **kwargs: calls.append((agent_id, kwargs)) or {'proposal': row})
    decision = {'proposal_id': 'p1', 'expected_fingerprint': 'a' * 64}
    assert local_actions.execute('preference_proposal_reject', decision, current, governed=True)['proposal']['status'] == 'rejected'
    assert calls == [('assistant', decision)]
    def failure(*args, **kwargs):
        raise RuntimeError('private path and content')
    monkeypatch.setattr(dialogue, 'virtual_human_preference_proposals', failure)
    with pytest.raises(ValueError, match='偏好建议操作结果未确认') as error:
        local_actions.execute('preference_proposals', {}, current)
    assert 'private' not in str(error.value)


def test_native_action_and_manage_tool_wrappers(monkeypatch, current):
    import json
    from tools import personal_assistant_tools as wrappers
    from core.infrastructure import native_runtime
    monkeypatch.setattr(wrappers, '_identity', lambda: current)
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: True)
    monkeypatch.setattr(actions, '_binding', (object(), object(), None))
    row = {'proposalId': 'p1', 'agentId': 'assistant', 'preferenceType': 'humor', 'candidateValue': 'off', 'status': 'rejected'}
    calls = []
    monkeypatch.setattr(dialogue, 'reject_virtual_human_preference_proposal', lambda agent_id, **kw: calls.append(agent_id) or {'proposal': row})
    index = json.loads(wrappers.personal_assistant_action_tool('index', {'query': 'preference_proposal_reject'}))
    assert index['actions'][0]['action'] == 'preference_proposal_reject'
    detail = json.loads(wrappers.personal_assistant_action_tool('describe', {'action': 'preference_proposal_reject'}))
    assert detail['governed'] is True
    decision = {'proposal_id': 'p1', 'expected_fingerprint': 'a' * 64}
    pending = json.loads(wrappers.personal_assistant_action_tool('preference_proposal_reject', decision))
    assert pending['status'] == 'approval_required' and not calls
    # The manage wrapper is called by the native executor after its per-call approval.
    approved = json.loads(wrappers.personal_assistant_manage_tool('preference_proposal_reject', json.dumps(decision)))
    assert approved['proposal']['status'] == 'rejected' and calls == ['assistant']


def test_dispatch_fields_are_closed_and_native_errors_do_not_escape(monkeypatch, current):
    class Service:
        def list_dispatches(self):
            return [{'dispatchId': 'ok', 'projectId': 'private text', 'nativeTaskId': 'sensitive / text',
                     'createdAt': 'private', 'receipt': {'status': 'awaiting_approval', 'resultSummary': 'private'}}]
    monkeypatch.setattr(actions, '_binding', (Service(), object(), None))
    row = local_actions.execute('dispatch_list', {}, current)['dispatches'][0]
    assert row['status'] == 'awaiting_approval' and row['projectId'] == row['nativeTaskId'] == row['createdAt'] == ''
    class Failed:
        def list_dispatches(self):
            raise RuntimeError('private path')
    monkeypatch.setattr(actions, '_binding', (Failed(), object(), None))
    with pytest.raises(ValueError, match='派遣引用暂不可用') as error:
        local_actions.execute('dispatch_list', {}, current)
    assert 'private' not in str(error.value)


def test_preference_approval_summary_is_scoped_and_bound(monkeypatch, current):
    import json
    from core.infrastructure import native_runtime
    from core.web.services import agent_directory_service as directory
    from core.web.services.session.tool_approvals import _assistant_management_summary
    row = {'proposalId': 'p1', 'agentId': 'assistant', 'preferenceType': 'address', 'candidateValue': '你好', 'status': 'pending'}
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: True)
    monkeypatch.setattr(directory, 'current_agent_runtime', lambda **kwargs: current)
    monkeypatch.setattr(dialogue, 'virtual_human_preference_proposals', lambda *_a, **_kw: {'proposals': [row]})
    listed = local_actions.execute('preference_proposals', {}, current)['proposals'][0]
    args = {'proposal_id': 'p1', 'expected_fingerprint': listed['fingerprint']}
    def summary(params):
        return _assistant_management_summary({'action': 'preference_proposal_accept', 'arguments_json': json.dumps(params)})
    valid = summary(args)
    assert valid['assistantTargets'] == args
    assert valid['assistantPreference'] == {'preferenceType': 'address', 'candidateValue': '你好', 'status': 'pending'}
    for invalid in ({'proposal_id': 'p1'}, {**args, 'extra': 1}, {**args, 'expected_fingerprint': '0' * 64}):
        assert summary(invalid)['assistantArgumentsInvalid'] is True
    monkeypatch.setattr(directory, 'current_agent_runtime', lambda **kwargs: {**current, 'agentId': 'other'})
    assert summary(args)['assistantArgumentsInvalid'] is True
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: False)
    assert summary(args) == {'assistantArgumentsInvalid': True}


@pytest.mark.parametrize('case', ['success', 'changed', 'expired', 'identity_changed'])
def test_native_approval_decision_binds_the_reviewed_proposal(tmp_path, monkeypatch, current, case):
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from core.infrastructure import native_runtime
    from core.web.services import agent_directory_service as directory
    from core.web.services.session import tool_approvals
    from tests.test_virtual_human_life_preferences import _proposal_service

    monkeypatch.setattr(native, '_AGENT_ID', 'agent-a')
    current['agentId'] = 'agent-a'
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: True)
    writes = []
    clock = [datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)]
    service = _proposal_service(tmp_path, clock=clock, writer_calls=writes)
    monkeypatch.setattr(dialogue, 'get_virtual_human_life_service', lambda: service)
    monkeypatch.setattr(actions, '_binding', (object(), object(), None))
    service.queue_conversation_message('agent-a', session_id='session-agent-a', client_submission_id='submission-1', content='短一点')
    row = service.propose_companion_preference('agent-a', session_id='session-agent-a', turn_id='turn-user-1', preference_type='verbosity', candidate_value='brief')['proposal']
    item = actions.execute_action('preference_proposals', {}, runtime=current)['proposals'][0]
    params = {'proposal_id': row['proposalId'], 'expected_fingerprint': item['fingerprint']}
    tool_args = {'action': 'preference_proposal_accept', 'arguments_json': json.dumps(params)}
    tool_approvals.reset_tool_approval_state()
    def call():
        token = directory._CURRENT_AGENT_RUNTIME.set(dict(current))
        try:
            return authorized_call()
        finally:
            directory._CURRENT_AGENT_RUNTIME.reset(token)
    def authorized_call():
        result = tool_approvals.authorize_or_wait(session_id='session', turn_id='turn-user-1', agent_id='agent-a',
            call_id='call', tool_name='personal_assistant_manage_tool', tool_args=tool_args, approval='always',
            risk='write', decision_fingerprint='decision', config_revision=1, config_hash='config',
            permission_preset='request_approval', timeout_seconds=5)
        if not result.allowed:
            return None
        return actions.execute_action('preference_proposal_accept', params, runtime=current, governed=True)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call)
            for _ in range(200):
                pending = tool_approvals.list_tool_approval_requests('session', status='pending')
                if pending:
                    break
                if future.done():
                    future.result()
                time.sleep(.01)
            assert pending
            summary = pending[0]['argumentSummary']
            assert summary['assistantPreference'] == {'preferenceType': 'verbosity', 'candidateValue': 'brief', 'status': 'pending'}
            assert summary['assistantTargets'] == params
            if case == 'changed':
                with service._lock_for('agent-a'):
                    service.store.append_jsonl('agent-a', 'conversation/preference_proposals.jsonl', {**row, 'candidateValue': 'detailed'})
            if case == 'expired':
                clock[0] += timedelta(days=8)
            if case == 'identity_changed':
                monkeypatch.setattr(native, '_AGENT_ID', 'agent-b')
            tool_approvals.resolve_tool_approval_request('session', pending[0]['requestId'], decision='accept')
            if case == 'success':
                assert future.result(timeout=5)['proposal']['status'] == 'accepted'
                assert len(writes) == 1
            else:
                with pytest.raises(ValueError): future.result(timeout=5)
                assert not writes
    finally:
        tool_approvals.reset_tool_approval_state()


def test_approval_fails_closed_for_oversized_and_decided_proposals(monkeypatch, current):
    import json
    from core.infrastructure import native_runtime
    from core.web.services import agent_directory_service as directory
    from core.web.services.session.tool_approvals import _assistant_management_summary
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: True)
    monkeypatch.setattr(directory, 'current_agent_runtime', lambda **kwargs: current)
    args = {'action': 'preference_proposal_reject', 'arguments_json': json.dumps({'proposal_id': 'p1', 'expected_fingerprint': 'a' * 64})}
    row = {'proposalId': 'p1', 'agentId': 'assistant', 'preferenceType': 'address', 'candidateValue': 'x' * 41, 'status': 'pending'}
    monkeypatch.setattr(dialogue, 'virtual_human_preference_proposals', lambda *_a, **_kw: {'proposals': [row]})
    assert _assistant_management_summary(args)['assistantArgumentsInvalid'] is True
    row['candidateValue'] = 'valid'; row['status'] = 'accepted'
    assert _assistant_management_summary(args)['assistantArgumentsInvalid'] is True


def test_address_approval_matches_normalized_native_preference_write(tmp_path, monkeypatch, current):
    from datetime import datetime, timezone
    from core.web.services import agent_directory_service as directory
    from core.assistant_runtime.discovery_actions import preference_approval_summary
    from tests.test_virtual_human_life_preferences import _proposal_service
    monkeypatch.setattr(native, '_AGENT_ID', 'agent-a')
    current['agentId'] = 'agent-a'
    monkeypatch.setattr(directory, 'current_agent_runtime', lambda **kwargs: current)
    service = _proposal_service(tmp_path, clock=[datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)])
    monkeypatch.setattr(dialogue, 'get_virtual_human_life_service', lambda: service)
    service.queue_conversation_message('agent-a', session_id='session-agent-a', client_submission_id='submission-1', content='请这样称呼我')
    row = service.propose_companion_preference('agent-a', session_id='session-agent-a', turn_id='turn-user-1', preference_type='address', candidate_value='小明')['proposal']
    # Native projection normalizes raw source records; approval and the native
    # writer must both use exactly that same effective value.
    raw_value = '  小明  ' + '称' * 60 + '  '
    with service._lock_for('agent-a'):
        service.store.append_jsonl('agent-a', 'conversation/preference_proposals.jsonl', {**row, 'candidateValue': raw_value})
    listed = local_actions.execute('preference_proposals', {}, current)['proposals'][0]
    params = {'proposal_id': row['proposalId'], 'expected_fingerprint': listed['fingerprint']}
    summary = preference_approval_summary('preference_proposal_accept', params)
    expected = (' '.join(raw_value.split()))[:40]
    assert summary['assistantPreference']['candidateValue'] == listed['candidateValue'] == expected
    local_actions.execute('preference_proposal_accept', params, current, governed=True)
    assert service.list_companion_preferences('agent-a')['values']['address'] == expected
