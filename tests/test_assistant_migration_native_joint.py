"""Retained migration archives survive real, isolated native process restarts."""

import json

from core.assistant_runtime import migration_history as history
from core.assistant_runtime.migration_source_archive import import_source_snapshots
from tests.test_assistant_migration_history import AGENT, discover, source
from tests.test_assistant_migration_source_archive import source as custom_source
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def _bytes_under(*roots):
    return {path: path.read_bytes() for root in roots for path in root.rglob("*") if path.is_file()}


def test_imported_history_survives_native_process_restart(tmp_path):
    workspace = source(tmp_path, [
        {"id": "direct", "agent_id": AGENT},
        {"id": "archived", "agentId": AGENT, "archived": True},
        {"id": "hidden", "parentSessionId": "direct", "hidden": True},
    ])
    originals = {}
    for sid in ("direct", "archived", "hidden"):
        path = workspace / "sessions" / sid / "turn_journal.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        # Long Unicode and JSON escapes force multiple character pages. The
        # expected body comes from source bytes, independently of projection.
        original = f'{sid}: 原文\\路径\n"quoted" ' * 90 + "结束"
        rows[1]["payload"].update(content=original, messageId=f"{sid}-user")
        rows[2]["payload"].update(content=f"{sid}: original answer", messageId=f"{sid}-answer")
        rows.insert(-1, dict(eventId=f"{sid}-tool-event", sessionId=sid, turnId="turn-1", sequence=4,
            eventType="assistant_item_committed", payload={"kind": "tool_call", "itemId": f"{sid}-item",
                "callId": f"{sid}-call", "revision": 0, "status": "completed", "text": "retained tool result"}))
        rows[-1]["sequence"] = 5
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        originals[sid] = original

    source_before = _bytes_under(workspace)
    root = tmp_path / "native"
    imported = history.import_history(discover(workspace), root, "joint-history")
    assert imported["published"] is True
    retained_before = _bytes_under(root / "history_archive")
    assert retained_before
    assert source_before == _bytes_under(workspace)
    expected = {"originals": originals, "sourceAgentId": AGENT}
    (tmp_path / "expected.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")

    # Each _run starts a new Python interpreter with launcher_assistant role,
    # an audited private home, and a loopback-only synthetic model provider.
    code = '''
        import json, os
        from pathlib import Path
        from core.assistant_runtime import local_actions, migration_history, native
        from core.chat.turn_journal import load_turn_events
        from core.web.services import agent_directory_service as directory, session_service as sessions
        from core.web.services.session import directory_runtime

        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        expected = json.loads((root.parent / 'expected.json').read_text(encoding='utf-8'))
        identity_path = root.parent / 'first-native-process.json'
        previous = json.loads(identity_path.read_text(encoding='utf-8')) if identity_path.exists() else None
        try:
            assistant = native.bootstrap(root)['assistant']
            identity = {key: assistant[key] for key in ('agentId', 'directSessionId')}
            assert identity['agentId'] != expected['sourceAgentId']
            assert identity['directSessionId'] not in expected['originals']
            assert native.get_detail(identity['directSessionId'])['id'] == identity['directSessionId']
            assert directory_runtime.directory_store_project_root() == root
            assert len(directory.list_agents(detail='summary')) == 1
            before_events = load_turn_events(root, identity['directSessionId'])
            assert before_events == []
            journal_before = {p: p.read_bytes() for p in root.rglob('turn_journal.jsonl')}
            runtime = {'agentId': identity['agentId'], 'sessionId': identity['directSessionId']}

            listing, offset, page_count = [], 0, 0
            while True:
                page = local_actions.execute('history_list', {'offset': offset, 'limit': 1}, runtime)
                assert page['total'] == 3 and page['offset'] == offset
                assert page['readOnly'] and page['untrustedContent']
                assert len(page['histories']) == 1
                assert '原文' not in json.dumps(page, ensure_ascii=False)
                listing.extend(page['histories'])
                page_count += 1
                offset = page['nextOffset']
                if offset is None:
                    break
                assert offset == page_count
            assert page_count == 3
            assert {row['sessionId'] for row in listing} == set(expected['originals'])
            assert len({row['historyId'] for row in listing}) == 3

            read_messages = {}
            for row in listing:
                sid, hid = row['sessionId'], row['historyId']
                assert row['sourceScope'] == {'projectId': 'project-1', 'instanceId': 'instance-1',
                                             'agentId': expected['sourceAgentId']}
                assert row['readOnly'] and row['untrustedContent'] and row['canContinue'] is False
                message_index, messages, chunks = 0, [], 0
                while True:
                    character_offset, parts = 0, []
                    while True:
                        result = local_actions.execute('history_read', {'history_id': hid,
                            'message_index': message_index, 'character_offset': character_offset,
                            'max_characters': 79}, runtime)
                        assert result['historyId'] == hid and result['sessionId'] == sid
                        assert result['messageIndex'] == message_index
                        assert result['characterOffset'] == character_offset
                        assert result['readOnly'] and result['untrustedContent'] and result['canContinue'] is False
                        assert all(key not in result for key in ('sourceBody', 'events', 'path', 'projectRoot'))
                        parts.append(result['text'])
                        chunks += 1
                        character_offset = result['nextCharacterOffset']
                        if character_offset is None:
                            break
                        assert character_offset == sum(map(len, parts))
                    messages.append(json.loads(''.join(parts)))
                    message_index = result['nextMessageIndex']
                    if message_index is None:
                        break
                    assert message_index == len(messages)
                assert chunks > 2 and len(messages) == 2, (chunks, len(messages))
                assert [message['content'] for message in messages] == [expected['originals'][sid], sid + ': original answer']
                assert [message['role'] for message in messages] == ['user', 'assistant']
                read_messages[hid] = messages

                detail = migration_history.history_detail(root, hid)
                assert detail['events'][1]['eventId'] == sid + '-e2'
                assert detail['events'][1]['payload']['messageId'] == sid + '-user'
                assert detail['events'][2]['eventId'] == sid + '-e3'
                assert detail['events'][2]['payload']['messageId'] == sid + '-answer'
                assert detail['turnItems'][0]['itemId'] == sid + '-item'
                assert sid + '-call' in json.dumps(detail['turnItems'])
                try:
                    native.get_detail(sid)
                except sessions.SessionNotFoundError:
                    pass
                else:
                    raise AssertionError('imported session entered native Session access')
                try:
                    local_actions.execute('history_read', {'history_id': hid, 'continue': True}, runtime)
                except ValueError:
                    pass
                else:
                    raise AssertionError('history accepted a continuation argument')
                try:
                    native.continue_turn('legacy-' + sid, {'turnId': 'turn-1', 'headId': sid + '-e5',
                        'ledgerSeq': 5, 'agentId': expected['sourceAgentId']})
                except native.AssistantSessionError:
                    pass
                else:
                    raise AssertionError('imported snapshot admitted a new native Turn')

            assert load_turn_events(root, identity['directSessionId']) == before_events
            assert {p: p.read_bytes() for p in root.rglob('turn_journal.jsonl')} == journal_before
            observed = {'identity': identity, 'histories': listing, 'messages': read_messages}
            if previous is None:
                identity_path.write_text(json.dumps({'pid': os.getpid(), **observed}), encoding='utf-8')
            else:
                assert previous['pid'] != os.getpid()
                assert observed == {key: previous[key] for key in observed}
        finally:
            assert native.shutdown()['closed']
            assert not directory_runtime.is_directory_store_open()
    '''
    for _ in range(2):
        _run(tmp_path, code, config_text=TEST_MODEL_CONFIG)
        assert source_before == _bytes_under(workspace)
        assert retained_before == _bytes_under(root / "history_archive")


def test_custom_source_archive_survives_native_restart_without_activating_queue(tmp_path):
    from core.assistant_runtime.migration_paths import _identity_chain

    project, workspace, external, snapshots = custom_source(tmp_path / "custom")
    source_before = _bytes_under(project, external)
    identities = {path: _identity_chain(path) for path in (project, workspace, external)}

    def verify_authority():
        assert identities == {path: _identity_chain(path) for path in identities}
        assert source_before == _bytes_under(project, external)

    root = tmp_path / "native"
    copied = import_source_snapshots(snapshots, root, "joint-sources", source_roots=(project, workspace),
                                     authority_verify=verify_authority)
    assert copied["published"] is True and copied["readyForCutover"] is False
    retained_before = _bytes_under(root / "history_sources")
    assert retained_before
    code = '''
        import json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.chat.turn_journal import load_turn_events
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        identity_path = root.parent / 'custom-first-process.json'
        try:
            assistant = native.bootstrap(root)['assistant']
            identity = {key: assistant[key] for key in ('agentId', 'directSessionId')}
            if identity_path.exists():
                assert json.loads(identity_path.read_text(encoding='utf-8')) == identity
            else:
                identity_path.write_text(json.dumps(identity), encoding='utf-8')
            manifest_path = root / 'history_sources/migrations/joint-sources/manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            assert manifest['readOnly'] and manifest['untrustedContent']
            assert manifest['activePluginStateImported'] is False
            assert manifest['readyForCutover'] is False
            assert {entry['category'] for entry in manifest['entries']} == {'memory'}
            assert len(manifest['entries']) == 1
            archive_bytes = (manifest_path.parent / manifest['entries'][0]['path']).read_bytes()
            assert archive_bytes == b'{"text":"PRIVATE_MEMORY"}\\n'
            assert not list(root.rglob('queue.json'))
            assert load_turn_events(root, identity['directSessionId']) == []
        finally:
            assert native.shutdown()['closed']
    '''
    for _ in range(2):
        _run(tmp_path, code, config_text=TEST_MODEL_CONFIG)
        assert source_before == _bytes_under(project, external)
        assert retained_before == _bytes_under(root / "history_sources")
