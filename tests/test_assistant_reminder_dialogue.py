from tests.test_assistant_migration_affairs_convergence import _fixture


def test_handoff_receipt_original_sync_id_reads_real_unresolved_conflict(tmp_path):
    _fixture(tmp_path, r'''
        import asyncio
        from core.assistant_runtime.actions import bind_actions, unbind_actions, execute_action
        from core.assistant_runtime.main_control import MainControlBroker
        from core.assistant_runtime.reminder_handoff_intent import handoff_id, sync_id
        class Dispatch:
            def project_ids(self): return ('registered:1',)
        project_id = 'registered:1'
        original_sync_id = sync_id(project_id)
        try:
            with owner.admit(**args) as lease:
                service = personal_affairs_service.get_personal_affairs_service()
                service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'title': 'user edit'}])
                ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
                before = ledger.read_bytes()
                prepare_affairs_conflicts(lease, baseline_migration_id='initial', snapshot_migration_id='latest',
                    sync_id=original_sync_id, source_scope=scope)
                assert reconcile_affairs(lease, sync_id=original_sync_id, source_scope=scope)['conflictCount'] == 1
                runtime = {'agentId': lease.agent_id, 'sessionId': lease.session_id}
                async def exchange():
                    dispatch = Dispatch()
                    broker = MainControlBroker(dispatch.project_ids, claim_seconds=2, initial_migration_enabled=True)
                    bind_actions(dispatch, asyncio.get_running_loop(), main_control=broker)
                    try:
                        description = execute_action('describe', {'action': 'reminder_handoff_receipt'})['description']
                        assert all(word in description for word in ('syncId', 'sync_id', 'affairs_conflict_list',
                            'affairs_conflict_read', 'unresolved', 'sender_proof_unavailable', '不自动覆盖', '不换 ID 重派'))
                        pending = asyncio.create_task(asyncio.to_thread(execute_action, 'reminder_handoff_receipt',
                            {'project_id': project_id}, runtime=runtime))
                        request = (await broker.claim())['request']
                        receipt = {'schemaVersion': 1, 'projectId': project_id, 'category': 'reminder_handoff',
                            'operationId': handoff_id(project_id), 'syncId': original_sync_id, 'state': 'pending',
                            'code': 'affairs_conflicts', 'conflictCount': 1, 'readyForCutover': False}
                        assert broker.settle(request['deliveryId'], receipt)
                        result = await pending
                        assert result['syncId'] == original_sync_id and result['readyForCutover'] is False
                        page = execute_action('affairs_conflict_list', {'sync_id': result['syncId']}, runtime=runtime)
                        conflict = next(x for x in page['conflicts'] if x['syncStatus'] == 'unresolved')
                        detail = execute_action('affairs_conflict_read', {'sync_id': result['syncId'],
                            'conflict_id': conflict['conflictId']}, runtime=runtime)
                        assert detail['syncStatus'] == 'unresolved' and detail['readOnly']
                        assert 'source' in detail['text'] and 'user edit' in detail['text']
                        assert ledger.read_bytes() == before
                    finally:
                        broker.close(); unbind_actions(dispatch)
                asyncio.run(exchange())
        finally:
            assert native.shutdown()['closed']
    ''')
