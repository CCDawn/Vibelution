"""Read-only original-ID receipts over the isolated native episodic ledger."""
from tests.test_assistant_online_episodic_sync import _SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_READER = r'''
import sys
from core.assistant_runtime import local_actions
runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
tracking = [False]
writes = []
def audit(event, args):
    if not tracking[0]: return
    if event == 'open' and not isinstance(args[0], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        writes.append(event)
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.replace'):
        writes.append(event)
sys.addaudithook(audit)
def receipt(mid):
    from core.assistant_runtime import online_episodic_sync as sync
    original_write, original_transaction = sync._write_receipt, episodes.episodic_transaction
    def forbidden(*args, **kwargs): raise AssertionError('receipt query invoked a writer')
    sync._write_receipt = forbidden; episodes.episodic_transaction = forbidden
    writes.clear(); tracking[0] = True
    try:
        result = local_actions.execute('episodic_sync_receipt', {'sync_id': mid}, runtime)
    finally:
        tracking[0] = False
        sync._write_receipt = original_write; episodes.episodic_transaction = original_transaction
    assert writes == [], writes
    assert result['syncId'] == mid and result['readOnly'] is True
    assert result['readyForCutover'] is False and result['sourceQuiesced'] is False
    assert 'C:/' not in json.dumps(result)
    return result
'''


def test_published_original_id_and_current_match_are_separate(tmp_path):
    _run(tmp_path, _SETUP + _READER + r'''
try:
    first, successor = 'episodic-' + '1' * 40, 'episodic-' + '2' * 40
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    third = {**old, 'episodeId': 'three', 'eventId': 'three'}
    archive(first, [old, second]); archive(successor, [old, second, third])
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=first)['appliedCount'] == 1
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = receipt(first)
    assert result['state'] == 'published' and result['targetMatch'] == 'matched'
    assert result['plannedAppliedCount'] == 1 and result['conflictCount'] == 0
    try: local_actions.execute('episodic_conflict_review', {'sync_id': first}, runtime)
    except ValueError as error: assert 'episodic_sync_receipt' in str(error)
    else: raise AssertionError('completed receipt was mistaken for a conflict')
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=successor)['appliedCount'] == 1
    result = receipt(first)
    assert result['state'] == 'published' and result['targetMatch'] == 'different'
    assert receipt(successor)['targetMatch'] == 'matched'
    from core.web.services import agent_directory_service as directory
    ledger = episodes._episodic_events_path(directory.get_agent(assistant['agentId']))
    lock = ledger.with_name(ledger.name + '.lock')
    if lock.exists(): lock.unlink()
    assert receipt(successor)['targetMatch'] == 'matched' and not lock.exists()
    ledger.unlink()
    result = receipt(first)
    assert result['state'] == 'published' and result['targetMatch'] == 'unknown'
    assert not ledger.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_partial_pending_and_missing_receipts_never_imply_no_execution(tmp_path):
    _run(tmp_path, _SETUP + _READER + r'''
try:
    absent = 'episodic-' + '0' * 40
    unknown = receipt(absent)
    assert unknown['state'] == 'unknown' and '不表示未执行' in unknown['notice']
    assert not (root / 'episodic_sync_receipts').exists()
    pending = 'episodic-' + '1' * 40
    archive(pending, [])
    from core.assistant_runtime import online_episodic_sync as sync
    original = sync._write_receipt
    def crash(path, value):
        if value['published']: raise RuntimeError('synthetic crash')
        original(path, value)
    sync._write_receipt = crash
    try:
        with owner.admit(**args) as lease:
            try: reconcile_episodic(lease, sync_id=pending)
            except RuntimeError: pass
            else: raise AssertionError('crash not injected')
    finally:
        sync._write_receipt = original
    result = receipt(pending)
    assert result['state'] == 'pending' and result['targetMatch'] == 'matched'
    assert result['plannedAppliedCount'] == 0 and result['conflictCount'] == 1
    path = root / 'episodic_sync_receipts' / (hashlib.sha256(pending.encode()).hexdigest() + '.json')
    assert json.loads(path.read_text())['published'] is False
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[0]['text'] = 'user edit'; tx._dirty = True
    changed = receipt(pending)
    assert changed['state'] == 'pending' and changed['targetMatch'] == 'different'
    assert json.loads(path.read_text())['published'] is False
    with episodes.episodic_transaction(assistant['agentId']) as tx:
        tx.events[0]['text'] = old['text']; tx._dirty = True
    with owner.admit(**args) as lease:
        assert reconcile_episodic(lease, sync_id=pending, confirmation_only=True)['conflictCount'] == 1
    result = receipt(pending)
    assert result['state'] == 'published' and result['conflictCount'] == 1 and result['targetMatch'] == 'matched'
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_damaged_successor_and_untrusted_caller_fail_closed(tmp_path):
    _run(tmp_path, _SETUP + _READER + r'''
try:
    first, successor = 'episodic-' + '1' * 40, 'episodic-' + '2' * 40
    second = {**old, 'episodeId': 'two', 'eventId': 'two'}
    third = {**old, 'episodeId': 'three', 'eventId': 'three'}
    archive(first, [old, second]); archive(successor, [old, second, third])
    with owner.admit(**args) as lease:
        reconcile_episodic(lease, sync_id=first)
        reconcile_episodic(lease, sync_id=successor)
    source = root / 'history_sources/migrations' / successor / 'sources/ref/episodic_events.jsonl'
    source.write_bytes(encoded([old]))
    assert receipt(first)['state'] == 'unknown'
    try: local_actions.execute('episodic_sync_receipt', {'sync_id': first}, {**runtime, 'agentId': 'other'})
    except ValueError: pass
    else: raise AssertionError('foreign agent accessed receipt')
    try: local_actions.execute('episodic_sync_receipt', {'sync_id': first, 'path': 'C:/secret'}, runtime)
    except ValueError: pass
    else: raise AssertionError('unexpected path was accepted')
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)
