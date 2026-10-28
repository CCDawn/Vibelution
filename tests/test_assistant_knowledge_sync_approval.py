"""Knowledge sync uses native policy approval and an explicit preview."""
import json

from core.web.services.session.tool_approvals import _assistant_management_summary


def test_knowledge_sync_approval_has_bound_source_and_rejects_injected_authority(monkeypatch):
    monkeypatch.setattr('core.infrastructure.native_runtime.is_launcher_assistant_process', lambda: True)
    monkeypatch.setattr('core.assistant_runtime.actions.history_import_approval_summary', lambda project, preview: {
        'sourceProjectId': 'source', 'instanceId': 'instance', 'assistantAgentId': 'agent'})
    values = {'project_id': 'registered:1', 'preview_id': 'a' * 64}
    result = _assistant_management_summary({'action': 'knowledge_sync_queue', 'arguments_json': json.dumps(values)})
    assert result['assistantTargets']['assistantAgentId'] == 'agent'
    assert '下次启动' in result['assistantOperationDescription']
    assert _assistant_management_summary({'action':'knowledge_sync_queue',
        'arguments_json':json.dumps({**values, 'approved':True})})['assistantArgumentsInvalid'] is True
    original = 'ksync-' + 'b' * 40
    recovery = _assistant_management_summary({'action':'knowledge_sync_recover',
        'arguments_json':json.dumps({**values, 'operation_id':original})})
    assert recovery['assistantTargets']['syncId'] == original
    assert '不重放未知写入' in recovery['assistantOperationDescription']
    assert _assistant_management_summary({'action':'knowledge_sync_recover',
        'arguments_json':json.dumps({**values, 'operation_id':'initial-' + 'b' * 40})})['assistantArgumentsInvalid'] is True
