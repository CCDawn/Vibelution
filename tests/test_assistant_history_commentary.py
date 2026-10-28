import json

import pytest

from core.assistant_runtime import history_actions as actions, local_actions, migration_history as history
from tests.test_assistant_migration_history import discover, source


def archive(tmp_path, monkeypatch, text):
    workspace = source(tmp_path)
    path = workspace / 'sessions/direct/turn_journal.jsonl'
    original = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    payloads = [
        {'kind': 'commentary', 'channel': 'commentary', 'phase': '', 'text': text,
         'input': 'SECRET_INPUT', 'metadata': {'value': 'SECRET_METADATA'}},
        {'kind': 'commentary', 'channel': 'commentary', 'text': {'input': 'SECRET_DICT'}},
        {'kind': 'commentary', 'channel': 'commentary', 'text': 'SECRET_CALL', 'callId': 'call'},
        {'kind': 'reasoning', 'channel': 'reasoning', 'text': 'SECRET_REASONING'},
        {'kind': 'tool_call', 'channel': 'commentary', 'text': 'SECRET_TOOL'},
        {'kind': 'assistant_message', 'channel': 'commentary', 'text': 'SECRET_FINAL'},
        {'kind': 'commentary', 'channel': 'commentary', 'text': 'Second visible'},
    ]
    events = original[:2]
    for payload in payloads:
        events.append({'eventId': f'item-{len(events)}', 'sessionId': 'direct', 'turnId': 'turn-1',
                       'eventType': 'assistant_item_committed', 'payload': payload})
    events.extend(original[2:])
    for i, event in enumerate(events, 1):
        event['sequence'] = i
    path.write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in events), encoding='utf-8')
    target = tmp_path / 'target'
    history.import_history(discover(workspace), target, 'one')
    monkeypatch.setattr(actions, 'assistant_native_root', lambda: target)
    hid = actions.execute('history_list', {})['histories'][0]['historyId']
    return workspace, target, hid


def test_real_archive_paging_excludes_non_commentary_and_binds_version(tmp_path, monkeypatch):
    text = '中文\\"\n' * 700
    workspace, target, hid = archive(tmp_path, monkeypatch, text)
    args = {'history_id': hid, 'max_characters': 1600}
    parts = []
    while True:
        result = local_actions.execute('history_commentary_read', args, {})
        assert result['untrustedContent'] and result['readOnly'] and not result['canContinue']
        assert len(json.dumps({**result, 'source': 'launcher-assistant'}, ensure_ascii=False).encode('utf-8')) <= 3300
        assert 'SECRET_' not in json.dumps(result)
        parts.append(result['text'])
        if result['nextCharacterOffset'] is None:
            break
        args.update(journal_sha256=result['journalSha256'], character_offset=result['nextCharacterOffset'])
    assert ''.join(parts) == text.strip()
    assert result['nextCommentaryIndex'] == 1
    second = local_actions.execute('history_commentary_read', {'history_id': hid,
        'journal_sha256': result['journalSha256'], 'commentary_index': 1}, {})
    assert second['text'] == 'Second visible' and second['nextCommentaryIndex'] is None
    journal = workspace / 'sessions/direct/turn_journal.jsonl'
    last = json.loads(journal.read_text(encoding='utf-8').splitlines()[-1])['sequence']
    with journal.open('a', encoding='utf-8') as stream:
        for i, kind in enumerate(('turn_started', 'turn_completed'), last + 1):
            stream.write(json.dumps({'eventId': f'new-{i}', 'sessionId': 'direct', 'turnId': 'turn-2',
                                     'sequence': i, 'eventType': kind, 'payload': {}}) + '\n')
    history.import_history(discover(workspace), target, 'two')
    assert actions.execute('history_commentary_read', args)['error'] == 'history_version_changed'


def test_continuation_requires_hash_and_unknown_parameters_rejected(tmp_path, monkeypatch):
    _, _, hid = archive(tmp_path, monkeypatch, 'visible')
    for args in ({'history_id': hid, 'character_offset': 1},
                 {'history_id': hid, 'commentary_index': 1},
                 {'history_id': hid, 'path': 'C:/private'}):
        with pytest.raises(ValueError):
            actions.execute('history_commentary_read', args)


def test_ordinary_process_cannot_read(monkeypatch):
    def denied():
        raise RuntimeError('ordinary')
    monkeypatch.setattr(actions, 'assistant_native_root', denied)
    with pytest.raises(ValueError):
        actions.execute('history_commentary_read', {'history_id': 'a' * 64})


def test_native_tool_wrapper_routes_and_bounds_output(tmp_path, monkeypatch):
    from core.assistant_runtime import actions as runtime_actions
    from core.infrastructure import native_runtime
    from tools import personal_assistant_tools as tool

    _, _, hid = archive(tmp_path, monkeypatch, '内容\\"\n' * 900)
    monkeypatch.setattr(tool, '_identity', lambda: {'agentId': 'assistant', 'sessionId': 'test'})
    monkeypatch.setattr(native_runtime, 'is_launcher_assistant_process', lambda: True)
    monkeypatch.setattr(runtime_actions, '_binding', (object(), object(), None))
    output = tool.personal_assistant_action_tool('history_commentary_read',
                                                 {'history_id': hid, 'max_characters': 1600})
    result = json.loads(output)
    assert result['source'] == 'launcher-assistant' and result['text']
    assert result['nextCharacterOffset'] and len(output.encode('utf-8')) <= 3300


def test_empty_history_has_an_explicit_empty_page(tmp_path, monkeypatch):
    workspace = source(tmp_path)
    target = tmp_path / 'target'
    history.import_history(discover(workspace), target, 'one')
    monkeypatch.setattr(actions, 'assistant_native_root', lambda: target)
    hid = actions.execute('history_list', {})['histories'][0]['historyId']
    result = actions.execute('history_commentary_read', {'history_id': hid})
    assert result['text'] == '' and result['nextCommentaryIndex'] is None
    assert len(result['journalSha256']) == 64 and result['scope'] == 'commentary_only'
