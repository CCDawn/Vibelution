"""Read-only current-Launcher access to native episodic memory."""
from tests.test_assistant_online_episodic_sync import _SETUP
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_ACTION = r'''
from core.assistant_runtime import local_actions
from core.web.services import agent_directory_service as directory
runtime = {'agentId': assistant['agentId'], 'sessionId': assistant['directSessionId']}
ledger = episodes._episodic_events_path(directory.get_agent(assistant['agentId']))
lock = ledger.with_name(ledger.name + '.lock')
def read(**params):
    return local_actions.execute('personal_memory_list', params, runtime)
def inventory():
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}
'''


def test_native_order_search_pagination_and_no_mutations(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    newest = episodes.append_episodic_event(assistant['agentId'], text='SYNTHETIC current note', kind='preference')
    middle = episodes.append_episodic_event(assistant['agentId'], text='SYNTHETIC historical note')
    episodes.supersede_episodic_event(assistant['agentId'], middle['episodeId'])
    original = episodes.list_episodic_events
    calls = []
    def native_list(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    episodes.list_episodic_events = native_list
    try:
        before = inventory()
        all_rows = read(limit=6)
        assert calls and calls[0][0] == (assistant['agentId'],)
        assert [row['episodeId'] for row in all_rows['items']] == [row['episodeId'] for row in original(assistant['agentId'], include_superseded=True)]
        assert all_rows['total'] == 3 and all_rows['readOnly'] and all_rows['untrustedContent']
        assert any(row['episodeId'] == middle['episodeId'] and row['validUntil'] for row in all_rows['items'])
        active = read(include_superseded=False)
        assert active['total'] == 2 and middle['episodeId'] not in {r['episodeId'] for r in active['items']}
        match = read(query='synthetic', limit=1)
        assert match['total'] == 2 and match['nextOffset'] == 1
        page = read(query='synthetic', limit=1, offset=1, snapshot_token=match['snapshotToken'])
        assert page['items'][0]['episodeId'] != match['items'][0]['episodeId']
        assert inventory() == before
    finally:
        episodes.list_episodic_events = original
    assert newest['episodeId'] in {r['episodeId'] for r in all_rows['items']}
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_missing_or_empty_lock_uses_stable_snapshot_and_creates_nothing(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    original = episodes.list_episodic_events
    historical = episodes.append_episodic_event(assistant['agentId'], text='SYNTHETIC historical')
    episodes.supersede_episodic_event(assistant['agentId'], historical['episodeId'])
    native_all = original(assistant['agentId'], include_superseded=True)
    native_current = original(assistant['agentId'], include_superseded=False)
    def forbidden(*args, **kwargs): raise AssertionError('native list would create or seed a lock')
    episodes.list_episodic_events = forbidden
    try:
        if lock.exists(): lock.unlink()
        before = inventory(); result = read()
        assert [r['episodeId'] for r in result['items']] == [r['episodeId'] for r in native_all]
        active = read(include_superseded=False)
        assert [r['episodeId'] for r in active['items']] == [r['episodeId'] for r in native_current]
        assert not lock.exists() and inventory() == before
        lock.write_bytes(b'')
        before = inventory(); result = read()
        assert result['total'] == 2 and lock.read_bytes() == b'' and inventory() == before
        lock.unlink(); ledger.unlink()
        before = inventory(); result = read()
        assert result['total'] == 0 and result['items'] == []
        assert not lock.exists() and not ledger.exists() and inventory() == before
    finally:
        episodes.list_episodic_events = original
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_unlocked_snapshot_change_is_never_returned(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    from core.assistant_runtime import personal_memory_actions as reader
    if lock.exists(): lock.unlink()
    original = reader.read_stable_file
    changed = []
    def race(path, cap):
        snapshot = original(path, cap)
        if Path(path) == ledger and not changed:
            changed.append(True)
            row = {**old, 'agentId': assistant['agentId'], 'text': 'newer concurrent value'}
            ledger.write_bytes(encoded([row]))
        return snapshot
    reader.read_stable_file = race
    try:
        try: read()
        except ValueError: pass
        else: raise AssertionError('stale unlocked snapshot was returned')
    finally:
        reader.read_stable_file = original
    assert changed and not lock.exists()
    assert read()['items'][0]['text'] == 'newer concurrent value'
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_unlocked_snapshot_pins_ledger_against_concurrent_writer(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    import threading
    from core.assistant_runtime import personal_memory_actions as reader
    if lock.exists(): lock.unlink()
    original = reader._project
    attempts = []
    def concurrent(rows, include_superseded):
        def write():
            try:
                ledger.write_bytes(encoded([{**old, 'agentId': assistant['agentId'], 'text': 'concurrent'}]))
                attempts.append('written')
            except OSError:
                attempts.append('blocked')
        worker = threading.Thread(target=write); worker.start(); worker.join(5)
        assert not worker.is_alive()
        return original(rows, include_superseded)
    reader._project = concurrent
    try:
        result = read()
    finally:
        reader._project = original
    assert attempts == ['blocked'] and result['items'][0]['text'] == 'old'
    assert not lock.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_identity_bounds_untrusted_data_and_snapshot_change(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    long_text = 'A' * 1000
    episodes.append_episodic_event(assistant['agentId'], text=long_text, kind='private_note')
    first = read(query='private_note', limit=1, max_characters=200)
    assert first['total'] == 1 and len(first['items'][0]['text']) == 200
    assert first['items'][0]['nextCharacterOffset'] == 200 and first['untrustedContent']
    following = read(query='private_note', limit=1, max_characters=200, character_offset=200,
                     snapshot_token=first['snapshotToken'])
    assert following['items'][0]['text'] == 'A' * 200
    for params in ({'offset': 1}, {'character_offset': 1, 'limit': 1}, {'agent_id': 'other'},
                   {'path': 'C:/secret'}, {'limit': 7}, {'include_superseded': 1}):
        try: read(**params)
        except ValueError: pass
        else: raise AssertionError('invalid arguments accepted: ' + repr(params))
    for foreign in ({**runtime, 'agentId': 'other'}, {**runtime, 'sessionId': 'other'}):
        try: local_actions.execute('personal_memory_list', {}, foreign)
        except ValueError: pass
        else: raise AssertionError('foreign runtime read personal memory')
    episodes.append_episodic_event(assistant['agentId'], text='SYNTHETIC later edit')
    try: read(query='private_note', limit=1, offset=1, snapshot_token=first['snapshotToken'])
    except ValueError: pass
    else: raise AssertionError('stale pagination accepted')
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_native_timestamp_and_long_text_are_available_in_both_read_modes(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    value = episodes.append_episodic_event(assistant['agentId'], text='Z' * 70000, occurred_at='operator timestamp')
    result = read(query='ZZZ', limit=1, max_characters=200)
    assert result['total'] == 1 and result['items'][0]['episodeId'] == value['episodeId']
    assert result['items'][0]['occurredAt'] == 'operator timestamp' and result['items'][0]['nextCharacterOffset'] == 200
    end = read(query='ZZZ', limit=1, character_offset=69990, snapshot_token=result['snapshotToken'])
    assert end['items'][0]['text'] == 'Z' * 10 and end['items'][0]['nextCharacterOffset'] is None
    lock.unlink()
    fallback = read(query='ZZZ', limit=1)
    assert fallback['items'][0]['episodeId'] == value['episodeId'] and not lock.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_disabled_memory_policy_blocks_writes_but_keeps_existing_reads(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    directory.update_agent_instance(assistant['agentId'], memory_policy={'enabled': False})
    before = inventory()
    result = read()
    assert result['items'][0]['text'] == 'old' and inventory() == before
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_action_is_discoverable_without_arbitrary_agent_or_path():
    from core.assistant_runtime import local_actions
    from core.assistant_runtime.actions import _index_page
    contract = local_actions.contracts()['personal_memory_list']
    assert contract['governed'] is False and contract['parameters']['additionalProperties'] is False
    assert not {'agent_id', 'path'} & contract['parameters']['properties'].keys()
    for query in ('情景记忆', '个人记忆'):
        actions = _index_page({'query': query}, {}, local_actions.contracts(), {})['actions']
        assert 'personal_memory_list' in {row['action'] for row in actions}


def test_large_native_ledger_search_cursor_and_no_writes(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    import json
    # A real native JSONL with more than 4096 rows and more than 4 MiB,
    # including equal sort keys and superseded rows.
    rows = []
    for i in range(5100):
        rows.append({**old, 'agentId': assistant['agentId'], 'episodeId': 'episode-%06d' % i,
            'eventId': 'episode-%06d' % i, 'occurredAt': 'same' if i < 3 else '%06d' % i,
            'validFrom': 'same', 'validUntil': 'finished' if i % 5 == 0 else '',
            'text': ('Needle ' if i % 3 == 0 else 'Other ') + 'x' * 850})
    # Two duplicate native ordering keys verify Python's stable sort semantics.
    rows[1]['episodeId'] = rows[0]['episodeId']
    ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    native_rows = episodes.list_episodic_events(assistant['agentId'], include_superseded=True)
    original = episodes.list_episodic_events
    def forbidden(*args, **kwargs): raise AssertionError('large scan loaded native list')
    episodes.list_episodic_events = forbidden
    try:
        before = inventory()
        first = read(limit=6)
        assert first['total'] == 5100 and first['nextCursor']
        assert [r['episodeId'] for r in first['items']] == [r['episodeId'] for r in native_rows[:6]]
        # Deep legacy offset advances by cursor past its 4096 limit.
        deep = read(limit=6, offset=4096, snapshot_token=first['snapshotToken'])
        assert deep['nextOffset'] is None and deep['nextCursor']
        following = read(limit=6, cursor=deep['nextCursor'], snapshot_token=first['snapshotToken'])
        assert [r['episodeId'] for r in following['items']] == [r['episodeId'] for r in native_rows[4102:4108]]
        search = read(query='Needle', include_superseded=False, limit=6)
        expected = [r for r in native_rows if not r['validUntil'] and 'needle' in r['text'].lower()]
        assert search['total'] == len(expected)
        assert [r['episodeId'] for r in search['items']] == [r['episodeId'] for r in expected[:6]]
        assert inventory() == before
        lock.unlink()
        before = inventory()
        assert read(query='Needle')['total'] == 1700
        assert inventory() == before and not lock.exists()
        ledger.write_text(ledger.read_text(encoding='utf-8') + json.dumps(rows[0]) + '\n', encoding='utf-8')
        try: read(cursor=first['nextCursor'], snapshot_token=first['snapshotToken'])
        except ValueError: pass
        else: raise AssertionError('stale large-ledger cursor accepted')
    finally:
        episodes.list_episodic_events = original
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_row_count_alone_uses_stream_and_scan_budget_is_explicit(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    import json
    from core.assistant_runtime import personal_memory_actions as reader
    rows = [{**old, 'agentId': assistant['agentId'], 'episodeId': 'episode-%06d' % i,
             'text': 'record %d' % i, 'occurredAt': '%06d' % i} for i in range(4100)]
    ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    assert ledger.stat().st_size < 4 * 1024 * 1024
    original = episodes.list_episodic_events
    episodes.list_episodic_events = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('native unbounded list'))
    try:
        assert read()['total'] == 4100
        # Scan cap is enforced before parsing and is reported as a limit, not an empty result.
        cap = reader._SCAN_CAP
        reader._SCAN_CAP = 128
        try:
            try: read()
            except ValueError as exc: assert '上限' in str(exc)
            else: raise AssertionError('scan budget ignored')
        finally: reader._SCAN_CAP = cap
    finally:
        episodes.list_episodic_events = original
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)


def test_large_unlocked_stream_pins_ledger_against_concurrent_writer(tmp_path):
    _run(tmp_path, _SETUP + _ACTION + r'''
try:
    import json, threading
    from core.assistant_runtime import personal_memory_actions as reader
    rows = [{**old, 'agentId': assistant['agentId'], 'episodeId': 'episode-%06d' % i,
             'text': 'record %d' % i} for i in range(4100)]
    ledger.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    if lock.exists(): lock.unlink()
    original = reader._select
    attempts = []
    def concurrent(source, args):
        def write():
            try:
                ledger.write_text('changed', encoding='utf-8')
                attempts.append('written')
            except OSError:
                attempts.append('blocked')
        worker = threading.Thread(target=write); worker.start(); worker.join(5)
        assert not worker.is_alive()
        return original(source, args)
    reader._select = concurrent
    try: result = read()
    finally: reader._select = original
    assert result['total'] == 4100 and attempts == ['blocked'] and not lock.exists()
finally:
    assert native.shutdown()['closed']
''', config_text=TEST_MODEL_CONFIG)
