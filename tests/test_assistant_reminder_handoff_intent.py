import os
import pytest

from tests.test_assistant_online_affairs_host import _HOST_SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_handoff_native_turn_approval_publishes_one_stable_pending_intent(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, httpx
from core.assistant_runtime.main_control import MainControlBroker
from core.assistant_runtime.host import create_app
from core.assistant_runtime.reminder_handoff_intent import handoff_id, sync_id, read_handoff_intent
from core.assistant_runtime.actions import bind_actions, unbind_actions, execute_action
async def run_case():
    broker=MainControlBroker(dispatch.project_ids, claim_seconds=2, initial_migration_enabled=True)
    app=create_app(native=object(),token='private-test-token',dispatch=dispatch,history_control=history_host,main_control=broker)
    bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
    args={'project_id':'registered:1','preview_id':value['previewId']}
    runtime={'agentId':assistant['agentId'],'sessionId':assistant['directSessionId'],'turnId':'turn-one'}
    try:
        denied=await asyncio.to_thread(execute_action,'reminder_handoff_queue',args,runtime=runtime)
        assert denied['status']=='approval_required'
        task=asyncio.create_task(asyncio.to_thread(execute_action,'reminder_handoff_queue',args,runtime=runtime,governed=True))
        wire=(await broker.claim())['request']
        assert wire['category']=='reminder_handoff' and wire['operationId']==handoff_id('registered:1')
        payload={key:wire[key] for key in ('projectId','previewId','turnId','category','operationId')}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1',headers={'Authorization':'Bearer private-test-token'}) as client:
            response=await client.post('/api/assistant/initial-migration/prepare',json={**payload,'deliveryId':wire['deliveryId'],'revision':1})
            assert response.status_code==200, response.text
            bound=response.json()
            assert bound['sourceScope']==scope and bound['syncId']==sync_id('registered:1')
            assert bound['baselineId'] is None and bound['baselineState']=='unknown' and bound['readyForCutover'] is False
            assert read_handoff_intent(target,'registered:1')==bound
            private=await client.post('/api/assistant/legacy-reminders/handoff-receipt',json={'projectId':'registered:1','revision':1})
            assert private.status_code==200 and private.json()['state']=='pending'
            source=await client.post('/api/assistant/legacy-reminders/handoff-source',json={'projectId':'registered:1','revision':1})
            assert source.status_code==200, source.text
            assert source.json()['operationId']==handoff_id('registered:1')
            stale=await client.post('/api/assistant/legacy-reminders/handoff-receipt',json={'projectId':'registered:1','revision':2})
            assert stale.status_code==409
        out={'schemaVersion':1,**{key:wire[key] for key in ('projectId','previewId','category','operationId')},
             'state':'queued','code':'queued','readyForCutover':False}
        assert broker.settle(wire['deliveryId'],out)
        assert (await task)==out
        receipt_task=asyncio.create_task(asyncio.to_thread(execute_action,'reminder_handoff_receipt',{'project_id':'registered:1'},runtime=runtime))
        receipt_wire=(await broker.claim())['request']
        assert receipt_wire['operationId']==handoff_id('registered:1') and receipt_wire['category']=='reminder_handoff'
        receipt={'schemaVersion':1,'projectId':'registered:1','category':'reminder_handoff','operationId':handoff_id('registered:1'),
                 'syncId':sync_id('registered:1'),'state':'queued','code':'queued','waitingFor':'window','readyForCutover':False}
        assert broker.settle(receipt_wire['deliveryId'],receipt)
        assert await receipt_task==receipt
    finally:
        broker.close();unbind_actions(dispatch)
try: asyncio.run(run_case())
finally: cleanup()
# A fresh Python process reads the same immutable authorization, rather than
# recovering it from the exited host's in-memory delivery state.
import subprocess, sys
script="from core.assistant_runtime.reminder_handoff_intent import read_handoff_intent; import sys; x=read_handoff_intent(sys.argv[1],sys.argv[2]); print(x['operationId'],x['syncId'],x['baselineState'])"
again=subprocess.run([sys.executable,'-c',script,str(target),'registered:1'],capture_output=True,text=True,check=True)
assert again.stdout.strip()==f"{handoff_id('registered:1')} {sync_id('registered:1')} unknown"
''', config_text=TEST_MODEL_CONFIG)


def test_cancelled_handoff_delivery_cannot_publish_intent(tmp_path):
    _run(tmp_path, _HOST_SETUP + r'''
import asyncio, httpx
from core.assistant_runtime.main_control import MainControlBroker
from core.assistant_runtime.host import create_app
from core.assistant_runtime.reminder_handoff_intent import handoff_id, read_handoff_intent
async def run_case():
    broker=MainControlBroker(dispatch.project_ids,claim_seconds=1,initial_migration_enabled=True)
    app=create_app(native=object(),token='private-test-token',dispatch=dispatch,history_control=history_host,main_control=broker)
    request={'projectId':'registered:1','previewId':value['previewId'],'turnId':'turn-one',
             'category':'reminder_handoff','operationId':handoff_id('registered:1')}
    task=asyncio.create_task(broker.invoke('initial_migration_queue',request,turn_id='turn-one'))
    wire=(await broker.claim())['request']
    broker.cancel_history_imports('turn-one')
    assert (await task)['state']=='unknown'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1',
        headers={'Authorization':'Bearer private-test-token'}) as client:
        response=await client.post('/api/assistant/initial-migration/prepare',json={**request,'deliveryId':wire['deliveryId'],'revision':1})
        assert response.status_code==409
    assert read_handoff_intent(target,'registered:1') is None
    broker.close()
try: asyncio.run(run_case())
finally: cleanup()
''', config_text=TEST_MODEL_CONFIG)


def test_handoff_approval_summary_is_scoped_and_identifies_operation(monkeypatch):
    from core.infrastructure import native_runtime
    from core.assistant_runtime import actions
    from core.web.services.session.tool_approvals import _assistant_management_summary
    args={'action':'reminder_handoff_queue','arguments_json':'{"project_id":"p","preview_id":"'+('a'*64)+'"}'}
    monkeypatch.setattr(native_runtime,'is_launcher_assistant_process',lambda: False)
    assert _assistant_management_summary(args)=={'assistantArgumentsInvalid':True}
    monkeypatch.setattr(native_runtime,'is_launcher_assistant_process',lambda: True)
    monkeypatch.setattr(actions,'history_import_approval_summary',lambda project_id, preview_id:
        {'sourceProjectId':'source','instanceId':'main','assistantAgentId':'old'})
    result=_assistant_management_summary(args)
    assert result['assistantAction']=='reminder_handoff_queue' and result['assistantTargets']['assistantAgentId']=='old'
    assert '不会立即停止' in result['assistantOperationDescription']


@pytest.mark.skipif(os.name != "nt", reason="native pinned target writes require Windows")
def test_interrupted_pending_publication_blocks_reissue(tmp_path):
    from core.assistant_runtime.reminder_handoff_intent import publish_handoff_intent, handoff_id, sync_id
    from core.assistant_runtime.migration_io import MigrationIOError
    directory=tmp_path / 'reminder_handoff_intents'
    directory.mkdir()
    (directory / ('.pending-' + 'a'*32)).mkdir()
    project='registered:1'
    identity={'device':'1','inode':'2','birthtimeNs':'3'}
    binding={'schemaVersion':1,'registeredProjectId':project,'sourceScope':{'projectId':'source','instanceId':'main','agentId':'agent'},
             'category':'reminder_handoff','turnId':'turn','operationId':handoff_id(project),'syncId':sync_id(project),'revision':1,
             'sourceIdentityDigest':'a'*64,'registryDigest':'b'*64,'targetIdentityDigest':'c'*64,
             'projectDirectory':identity,'workspaceDirectory':identity,'targetDirectory':identity,'targetAgentId':'target',
             'targetSessionId':'session','authority':'native_policy_admitted','baselineId':None,'baselineState':'unknown','readyForCutover':False}
    class Token:
        def publish(self, write): raise AssertionError('must not publish')
    with pytest.raises(MigrationIOError,match='publication_unknown'):
        publish_handoff_intent(tmp_path,binding,Token(),lambda: None)
    assert not any(x.name != '.pending-' + 'a'*32 for x in directory.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="native pinned target writes require Windows")
@pytest.mark.parametrize("failure", ["cancelled", "source_changed"])
def test_prepublication_failure_removes_only_owned_staging_and_allows_other_project(tmp_path, failure):
    from core.assistant_runtime.reminder_handoff_intent import publish_handoff_intent, handoff_id, sync_id
    def binding(project):
        identity={'device':'1','inode':'2','birthtimeNs':'3'}
        return {'schemaVersion':1,'registeredProjectId':project,'sourceScope':{'projectId':'source','instanceId':'main','agentId':'agent'},
                'category':'reminder_handoff','turnId':'turn','operationId':handoff_id(project),'syncId':sync_id(project),'revision':1,
                'sourceIdentityDigest':'a'*64,'registryDigest':'b'*64,'targetIdentityDigest':'c'*64,
                'projectDirectory':identity,'workspaceDirectory':identity,'targetDirectory':identity,'targetAgentId':'target',
                'targetSessionId':'session','authority':'native_policy_admitted','baselineId':None,'baselineState':'unknown','readyForCutover':False}
    class Token:
        def __init__(self, cancelled=False): self.cancelled=cancelled
        def publish(self, write):
            if self.cancelled: raise ValueError('cancelled')
            return write()
        def check(self): pass
    def verify():
        if failure == 'source_changed': raise ValueError('source changed')
    with pytest.raises(ValueError):
        publish_handoff_intent(tmp_path,binding('first'),Token(failure == 'cancelled'),verify)
    directory=tmp_path / 'reminder_handoff_intents'
    assert list(directory.iterdir()) == []
    result=publish_handoff_intent(tmp_path,binding('second'),Token(),lambda: None)
    assert result['registeredProjectId']=='second'


@pytest.mark.skipif(os.name != "nt", reason="native pinned target writes require Windows")
def test_uncertain_started_publication_retains_staging(tmp_path, monkeypatch):
    from core.assistant_runtime import reminder_handoff_intent as handoff
    identity={'device':'1','inode':'2','birthtimeNs':'3'}
    project='registered:1'
    binding={'schemaVersion':1,'registeredProjectId':project,'sourceScope':{'projectId':'source','instanceId':'main','agentId':'agent'},
             'category':'reminder_handoff','turnId':'turn','operationId':handoff.handoff_id(project),'syncId':handoff.sync_id(project),'revision':1,
             'sourceIdentityDigest':'a'*64,'registryDigest':'b'*64,'targetIdentityDigest':'c'*64,
             'projectDirectory':identity,'workspaceDirectory':identity,'targetDirectory':identity,'targetAgentId':'target',
             'targetSessionId':'session','authority':'native_policy_admitted','baselineId':None,'baselineState':'unknown','readyForCutover':False}
    class Token:
        def publish(self, write): return write()
        def check(self): pass
    monkeypatch.setattr(handoff, 'publish_directory', lambda *args: (_ for _ in ()).throw(ValueError('outcome unknown')))
    with pytest.raises(ValueError): handoff.publish_handoff_intent(tmp_path,binding,Token(),lambda: None)
    assert len(list((tmp_path / 'reminder_handoff_intents').glob('.pending-*'))) == 1


@pytest.mark.skipif(os.name != "nt", reason="native pinned target writes require Windows")
def test_changed_staged_file_is_never_deleted(tmp_path):
    from core.assistant_runtime import reminder_handoff_intent as handoff
    identity={'device':'1','inode':'2','birthtimeNs':'3'}
    project='registered:1'
    binding={'schemaVersion':1,'registeredProjectId':project,'sourceScope':{'projectId':'source','instanceId':'main','agentId':'agent'},
             'category':'reminder_handoff','turnId':'turn','operationId':handoff.handoff_id(project),'syncId':handoff.sync_id(project),'revision':1,
             'sourceIdentityDigest':'a'*64,'registryDigest':'b'*64,'targetIdentityDigest':'c'*64,
             'projectDirectory':identity,'workspaceDirectory':identity,'targetDirectory':identity,'targetAgentId':'target',
             'targetSessionId':'session','authority':'native_policy_admitted','baselineId':None,'baselineState':'unknown','readyForCutover':False}
    class Token:
        def publish(self, write):
            pending=next((tmp_path / 'reminder_handoff_intents').glob('.pending-*'))
            (pending / 'intent.json').write_text('changed by another owner',encoding='utf-8')
            raise ValueError('cancelled')
    with pytest.raises(ValueError): handoff.publish_handoff_intent(tmp_path,binding,Token(),lambda: None)
    pending=next((tmp_path / 'reminder_handoff_intents').glob('.pending-*'))
    assert (pending / 'intent.json').read_text(encoding='utf-8')=='changed by another owner'
