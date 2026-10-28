"""Incremental queues inherit the native Turn's cancellation fence."""
import asyncio

import pytest

from core.assistant_runtime.main_control import MainControlBroker, _request, initial_migration_id, knowledge_sync_id, knowledge_recovery_id


def test_initial_and_incremental_ids_cannot_be_interchanged():
    preview = 'a' * 64
    incremental = knowledge_sync_id('project', preview)
    initial = initial_migration_id('project', '', 'knowledge')
    request = {'projectId':'project', 'previewId':preview, 'turnId':'turn', 'category':'knowledge_sync', 'operationId':incremental}
    assert _request('initial_migration_queue', request) == request
    for changed in ({**request, 'operationId':initial}, {**request, 'category':'knowledge'}):
        with pytest.raises(ValueError):
            _request('initial_migration_queue', changed)
    with pytest.raises(ValueError):
        _request('initial_migration_receipt', {'projectId':'project', 'category':'knowledge_sync', 'operationId':incremental})
    recovery = {**request, 'category':'knowledge_recovery', 'originalSyncId':incremental,
                'operationId':knowledge_recovery_id('project', preview, incremental)}
    assert _request('initial_migration_queue', recovery) == recovery
    for changed in ({**recovery, 'originalSyncId':'ksync-' + 'c' * 40}, {**recovery, 'operationId':incremental},
                    {key:value for key,value in recovery.items() if key != 'originalSyncId'}):
        with pytest.raises(ValueError):
            _request('initial_migration_queue', changed)


def test_stop_before_claim_rejects_without_publication():
    async def run():
        broker = MainControlBroker(lambda: ['project'], initial_migration_enabled=True)
        request = {'projectId':'project', 'previewId':'a' * 64, 'turnId':'turn', 'category':'knowledge_sync',
                   'operationId':knowledge_sync_id('project', 'a' * 64)}
        task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn'))
        await asyncio.sleep(0)
        broker.cancel_history_imports('turn')
        assert (await task)['state'] == 'rejected'
        broker.close()
    asyncio.run(run())


def test_stop_after_admission_revokes_publication_and_keeps_outcome_unknown():
    async def run():
        broker = MainControlBroker(lambda: ['project'], initial_migration_enabled=True)
        request = {'projectId':'project', 'previewId':'a' * 64, 'turnId':'turn', 'category':'knowledge_sync',
                   'operationId':knowledge_sync_id('project', 'a' * 64)}
        task = asyncio.create_task(broker.invoke('initial_migration_queue', request, turn_id='turn'))
        wire = (await broker.claim())['request']
        token = broker.initial_delivery(wire['deliveryId'], request, admit=True)
        assert token
        broker.begin_initial_fence('turn')
        writes = []
        with pytest.raises(ValueError):
            token.publish(lambda: writes.append(True))
        assert not writes and (await task)['state'] == 'unknown'
        token.finished()
        broker.end_initial_fence('turn')
        broker.close()
    asyncio.run(run())
