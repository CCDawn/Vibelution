"""Fresh native approval binds the current source to the same old handoff."""
import pytest

from tests.test_assistant_online_affairs_host import _HOST_SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


@pytest.mark.parametrize("flag", [False, None, 1, "true"])
def test_reminder_recovery_wire_rejects_nonliteral_flags(flag):
    from core.assistant_runtime.main_control import _request, initial_migration_id
    from core.assistant_runtime.host import InitialMigrationPrepare

    request = {"projectId": "project", "previewId": "a" * 64, "turnId": "turn",
               "category": "reminder_handoff", "operationId": initial_migration_id("project", "", "reminder_handoff")}
    with pytest.raises(ValueError):
        _request("initial_migration_queue", {**request, "reauthorize": flag})
    with pytest.raises(ValueError):
        InitialMigrationPrepare(**request, reauthorize=flag, deliveryId="b" * 32, revision=1)


def test_reminder_recovery_wire_is_additive_and_reminder_only():
    from core.assistant_runtime.main_control import _request, initial_migration_id
    for category in ("personal", "knowledge", "reminder_handoff"):
        request = {"projectId": "project", "previewId": "a" * 64, "turnId": "turn",
                   "category": category, "operationId": initial_migration_id("project", "", category)}
        assert _request("initial_migration_queue", request) == request
        if category == "reminder_handoff":
            assert _request("initial_migration_queue", {**request, "reauthorize": True})["reauthorize"] is True
        else:
            with pytest.raises(ValueError):
                _request("initial_migration_queue", {**request, "reauthorize": True})


@pytest.mark.parametrize("case", ["success", "missing_approval", "source_changed", "cancelled", "declined_then_retry", "head_changed"])
def test_native_original_id_recovery_needs_same_displayed_approval(tmp_path, case):
    _run(tmp_path, _HOST_SETUP + "\ncase = " + repr(case) + r'''
import asyncio, httpx
from core.assistant_runtime.actions import bind_actions, unbind_actions, execute_action
from core.assistant_runtime.main_control import MainControlBroker
from core.assistant_runtime.host import create_app
from core.assistant_runtime.reminder_handoff_intent import handoff_id, read_handoff_intent
from core.web.services.session.tool_approvals import (_assistant_management_summary, authorize_or_wait,
    list_tool_approval_requests, resolve_tool_approval_request, ToolApprovalConflictError)
class Token:
    def check(self): pass
    def publish(self, write): write()
history_host._initial_owner_check = lambda: True  # Explicit synthetic owner; production uses the OS lease.
original = history_host.prepare_initial_source('registered:1', value['previewId'], 1, 'turn-one',
    handoff_id('registered:1'), 'reminder_handoff', Token())
base_path = next((target / 'reminder_handoff_intents').glob('*/intent.json'))
base_bytes = base_path.read_bytes()
old_registry = json.loads(registry.read_text())
old_registry['agents'][0]['displayName'] = 'current registered source'
registry.write_text(json.dumps(old_registry))
fresh = preview.preview('registered:1', turn_id='turn-one')
dispatch.history_preview = preview  # Same composition as scripts/assistant_host.py.
async def run_case():
    broker = MainControlBroker(dispatch.project_ids, initial_migration_enabled=True)
    app = create_app(native=object(), token='private-test-token', dispatch=dispatch,
                     history_control=history_host, main_control=broker)
    bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
    args = {'project_id': 'registered:1', 'preview_id': fresh['previewId']}
    runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId'], 'turnId': 'turn-one'}
    task = None
    try:
        denied = await asyncio.to_thread(execute_action, 'reminder_handoff_recover', args, runtime=runtime)
        assert denied['status'] == 'approval_required'
        summary = _assistant_management_summary({'action': 'reminder_handoff_recover',
                                                'arguments_json': json.dumps(args)})
        assert summary.get('assistantArgumentsInvalid') is not True, summary
        assert summary['assistantTargets']['operationId'] == original['operationId']
        assert summary['assistantTargets']['syncId'] == original['syncId']
        assert '旧进程实际权限' in summary['assistantOperationDescription']
        # A repeated rendering cannot replace the already displayed binding.
        assert _assistant_management_summary({'action':'reminder_handoff_recover','arguments_json':json.dumps(args)}) == summary
        if case != 'missing_approval':
            # Even full_access must create a real native card for this one action.
            def authorized_call():
                if case == 'success':
                    from types import SimpleNamespace
                    from core.authorization import tool_authorization_service as authorization
                    from core.infrastructure.tool_executor import ToolExecutor
                    from core.web.services import agent_directory_service as directory
                    directory.current_agent_runtime = lambda: {
                        **runtime, 'agentConfigSnapshot':{'configRevision':1,'configHash':'synthetic-config'},
                        'permissionPreset':'full_access',
                        'collaborationMode':{'mode':'yolo','planEnabled':False,'prePlanMode':'build'}}
                    authorization.install_execution_authorization(SimpleNamespace(decision=SimpleNamespace(
                        agent_id=assistant['agentId'],turn_id='turn-one',decision_fingerprint='synthetic-recovery',
                        executable_tools=('personal_assistant_manage_tool',))))
                    executor = ToolExecutor()
                    def managed(action, arguments_json):
                        return json.dumps(execute_action(action,json.loads(arguments_json),runtime=runtime,governed=True))
                    executor.register_tool('personal_assistant_manage_tool',managed,timeout=10)
                    try:
                        return executor.execute('personal_assistant_manage_tool',
                            {'action':'reminder_handoff_recover','arguments_json':json.dumps(args)},tool_call_id='recovery-call')
                    finally: authorization.clear_execution_authorization()
                outcome = authorize_or_wait(
                    session_id=assistant['directSessionId'], turn_id='turn-one', agent_id=assistant['agentId'],
                    call_id='recovery-call', tool_name='personal_assistant_manage_tool',
                    tool_args={'action':'reminder_handoff_recover','arguments_json':json.dumps(args)},
                    approval='never', risk='destructive', decision_fingerprint='synthetic-recovery',
                    config_revision=1, config_hash='synthetic-config', permission_preset='full_access', timeout_seconds=3)
                if not outcome.allowed: return outcome
                # Same context is copied into the tool thread by ToolExecutor.
                from contextvars import copy_context
                return copy_context().run(execute_action, 'reminder_handoff_recover', args, runtime=runtime, governed=True)
            task = asyncio.create_task(asyncio.to_thread(authorized_call))
            for _ in range(300):
                pending = list_tool_approval_requests(assistant['directSessionId'], status='pending')
                if pending: break
                if task.done(): await task
                await asyncio.sleep(.01)
            assert pending and pending[-1]['callId'] == 'recovery-call'
            assert pending[-1]['availableDecisions'] == ['accept', 'decline', 'cancel'], pending[-1]['availableDecisions']
            resolve_tool_approval_request(assistant['directSessionId'], pending[-1]['requestId'],
                decision='decline' if case == 'declined_then_retry' else 'accept')
            if case == 'declined_then_retry':
                assert not (await task).allowed
                try:
                    await asyncio.to_thread(authorize_or_wait,
                        session_id=assistant['directSessionId'],turn_id='turn-one',agent_id=assistant['agentId'],
                        call_id='different-call',tool_name='personal_assistant_manage_tool',
                        tool_args={'action':'reminder_handoff_recover','arguments_json':json.dumps(args)},
                        approval='never',risk='destructive',decision_fingerprint='synthetic-recovery',
                        config_revision=1,config_hash='synthetic-config',permission_preset='full_access',timeout_seconds=.1)
                    raise AssertionError('declined card must not authorize a different call')
                except ToolApprovalConflictError: pass
                assert read_handoff_intent(target, 'registered:1') == original
                assert base_path.read_bytes() == base_bytes
                return
        else:
            # A displayed summary and a forged governed flag are not the
            # executor's accepted per-call authorization context.
            result = await asyncio.to_thread(execute_action, 'reminder_handoff_recover', args, runtime=runtime, governed=True)
            assert result['status'] == 'approval_required'
            assert read_handoff_intent(target, 'registered:1') == original
            assert base_path.read_bytes() == base_bytes
            return
        wire = (await broker.claim())['request']
        assert wire['reauthorize'] is True and wire['operationId'] == original['operationId']
        expected_prior = original
        if case == 'head_changed':
            from core.assistant_runtime.reminder_handoff_intent import publish_handoff_intent, read_handoff_authorization
            prior, head = read_handoff_authorization(target, 'registered:1')
            expected_prior = {**prior, 'registryDigest':'e'*64, 'turnId':'competing-turn'}
            publish_handoff_intent(target,expected_prior,Token(),lambda:None,expected_head=head,owner_check=lambda:True)
        if case == 'source_changed':
            changed = json.loads(registry.read_text()); changed['agents'][0]['displayName'] = 'changed after display'
            registry.write_text(json.dumps(changed))
        payload = {key: wire[key] for key in ('projectId','previewId','turnId','category','operationId','reauthorize')}
        if case == 'cancelled':
            broker.cancel_history_imports('turn-one')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1',
                                    headers={'Authorization':'Bearer private-test-token'}) as client:
            response = await client.post('/api/assistant/initial-migration/prepare',
                json={**payload, 'deliveryId':wire['deliveryId'], 'revision':1})
        if case == 'success':
            assert response.status_code == 200, response.text
            renewed = read_handoff_intent(target, 'registered:1')
            assert renewed['registryDigest'] != original['registryDigest']
            assert renewed['operationId'] == original['operationId'] and renewed['syncId'] == original['syncId']
            assert renewed['readyForCutover'] is False
            queued = {'schemaVersion':1,**{key:wire[key] for key in ('projectId','previewId','category','operationId')},
                      'state':'queued','code':'queued','readyForCutover':False}
            assert broker.settle(wire['deliveryId'],queued)
            result, action = await task
            assert json.loads(result) == queued and action is None
        else:
            assert response.status_code == 409, response.text
            assert read_handoff_intent(target, 'registered:1') == expected_prior
        assert base_path.read_bytes() == base_bytes
    finally:
        broker.close()
        if task is not None: await task
        unbind_actions(dispatch)
try: asyncio.run(run_case())
finally: cleanup()
''', config_text=TEST_MODEL_CONFIG)
