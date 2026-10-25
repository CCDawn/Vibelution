"""Existing native personal tools in a fresh, audited Launcher process."""

from __future__ import annotations

import pytest

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_personal_affairs_root_is_the_frozen_launcher_profile(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.web.services import personal_affairs_service as affairs
        expected = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        assert affairs.PROJECT_ROOT == expected
        os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'] = str(expected / 'changed')
        os.environ['VIBELUTION_PROCESS_ROLE'] = 'workbench'
        service = affairs.get_personal_affairs_service()
        assert service.store.project_root == expected
        assert service.store.plugin_root('own-agent').is_relative_to(expected)
    """, config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("developer_mode", [False, True])
def test_native_personal_tools_persist_own_affairs_and_private_memory_across_process_restart(tmp_path, developer_mode):
    config = TEST_MODEL_CONFIG + ("\n[launcher.developer_mode]\nenabled = true\n" if developer_mode else "")
    _run(tmp_path, """
        import json, os, sys
        from pathlib import Path
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('personal tools must not contact a provider')
        sys.addaudithook(no_network)
        os.environ['LANGCHAIN_TRACING_V2'] = 'false'
        os.environ['LANGCHAIN_TRACING'] = 'false'
        from core.assistant_runtime import native
        from core.web.services import agent_directory_service as directory, personal_affairs_service
        from core.web.services.agent_directory import episodic_memory
        from tools.Key_Tools import create_key_tools
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        expected = {'personal_assistant_action_tool', 'personal_assistant_manage_tool', 'personal_affairs_tool',
            'append_personal_memory_tool', 'supersede_personal_memory_tool', 'search_agent_private_memory_tool', 'compress_context_tool'}
        try:
            identity = native.bootstrap(root)['assistant']
            aid, sid = identity['agentId'], identity['directSessionId']
            tools = {tool.name: tool for tool in create_key_tools()}
            assert expected <= tools.keys()
            assert set(directory.get_agent(aid)['toolPolicy']['allowedTools']) == expected
            # These are the canonical descriptors, not same-named Launcher actions.
            assert tools['personal_affairs_tool'].func.__module__ == 'tools.personal_affairs_tools'
            assert set(tools['compress_context_tool'].args) == {'reason'}
            for name in expected - {'personal_assistant_action_tool', 'personal_assistant_manage_tool'}:
                assert not {'agent_id', 'session_id', 'project_root', 'root'} & tools[name].args.keys()
            def invoke(name, args):
                value = json.loads(tools[name].invoke(args))
                assert value.get('ok') is True, (name, value)
                return value
            with directory.active_agent_runtime(aid, session_id=sid, turn_id='personal-tools-test') as context:
                assert directory.current_agent_runtime()['sessionId'] == sid
                assert expected <= set(context['toolPolicy']['allowedTools']), context['toolPolicy']['allowedTools']
                assert not {'personal_assistant_query_tool', 'personal_assistant_platform_api_tool', 'agent_message_tool',
                    'personal_assistant_computer_action_tool'} & set(context['toolPolicy']['allowedTools'])
                assert invoke('personal_affairs_tool', {'action': 'list', 'kind': ''})['affairs']['items'] == []
                item = invoke('personal_affairs_tool', {'action': 'add', 'title': '自己的事务', 'kind': 'todo',
                    'note': 'private fixture', 'source_turn_id': 'personal-tools-test'})['item']
                item_id = item['itemId']
                for action, status in [('complete', 'done'), ('cancel', 'cancelled'), ('reopen', 'open')]:
                    observed = invoke('personal_affairs_tool', {'action': action, 'item_id': item_id})['item']
                    assert observed['itemId'] == item_id and observed['status'] == status
                updated = invoke('personal_affairs_tool', {'action': 'set_due', 'item_id': item_id,
                    'due_at': '2030-01-02T03:04:05+08:00'})['item']
                assert updated['itemId'] == item_id and updated['dueAt'] == '2030-01-01T19:04:05+00:00'
                rows = invoke('personal_affairs_tool', {'action': 'list', 'kind': ''})['affairs']['items']
                assert len(rows) == 1 and rows[0]['itemId'] == item_id and rows[0]['status'] == 'open'
                ledger = personal_affairs_service.get_personal_affairs_service().store._path(aid, 'affairs/items.jsonl')
                assert ledger.is_relative_to(root) and ledger.is_file()
                appended = invoke('append_personal_memory_tool', {'text': '旧的私人偏好_FIXTURE', 'kind': 'preference'})
                first_id = appended['episodeId']
                assert appended['agentId'] == aid and first_id
                replaced = invoke('supersede_personal_memory_tool', {'episode_id': first_id,
                    'successor_text': '新的私人偏好_FIXTURE', 'kind': 'preference'})
                successor_id = replaced['successorEpisodeId']
                assert replaced['episodeId'] == first_id and successor_id != first_id and replaced['validUntil']
                events = episodic_memory.list_episodic_events(aid, include_superseded=True)
                assert {row['episodeId'] for row in events} == {first_id, successor_id}
                assert all(row['agentId'] == aid for row in events)
                assert any(ref.get('id') == sid for row in events for ref in row.get('refs', []))
                prompt = directory.build_agent_runtime_context_block(aid)
                assert '新的私人偏好_FIXTURE' in prompt and '旧的私人偏好_FIXTURE' not in prompt
                empty = invoke('search_agent_private_memory_tool', {'query': '不存在的私有正式知识'})
                assert empty['status'] == 'empty' and empty['summary']['resultCount'] == 0
                assert empty['results'] == [] and empty['citations'] == []
                # Compression stays bound to this Session through its existing
                # native descriptor. No model-backed compression is run here.
                assert directory.current_agent_runtime()['agentId'] == aid
            (root / 'personal-test-ids.json').write_text(json.dumps({'agentId': aid, 'sessionId': sid,
                'itemId': item_id, 'episodeId': first_id, 'successorEpisodeId': successor_id}), encoding='utf-8')
        finally:
            assert native.shutdown()['closed']
    """, config_text=config)
    _run(tmp_path, """
        import json, os, sys
        from pathlib import Path
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('personal recovery must not contact a provider')
        sys.addaudithook(no_network)
        from core.assistant_runtime import native
        from core.web.services import agent_directory_service as directory
        from core.web.services.agent_directory import episodic_memory
        from tools.personal_affairs_tools import personal_affairs_tool
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        old = json.loads((root / 'personal-test-ids.json').read_text(encoding='utf-8'))
        try:
            current = native.bootstrap(root)['assistant']
            assert (current['agentId'], current['directSessionId']) == (old['agentId'], old['sessionId'])
            with directory.active_agent_runtime(old['agentId'], session_id=old['sessionId'], turn_id='personal-recovery-test'):
                rows = json.loads(personal_affairs_tool(action='list', kind=''))['affairs']['items']
                assert len(rows) == 1 and rows[0]['itemId'] == old['itemId'] and rows[0]['status'] == 'open'
                assert rows[0]['dueAt'] == '2030-01-01T19:04:05+00:00'
                events = episodic_memory.list_episodic_events(old['agentId'], include_superseded=True)
                assert {row['episodeId'] for row in events} == {old['episodeId'], old['successorEpisodeId']}
                original = next(row for row in events if row['episodeId'] == old['episodeId'])
                assert original['validUntil'] and original['supersededByEpisodeId'] == old['successorEpisodeId']
                prompt = directory.build_agent_runtime_context_block(old['agentId'])
                assert '新的私人偏好_FIXTURE' in prompt and '旧的私人偏好_FIXTURE' not in prompt
        finally:
            assert native.shutdown()['closed']
    """, config_text=config)


@pytest.mark.parametrize("allowed", [[], ["personal_assistant_action_tool"]])
def test_existing_empty_or_custom_profile_never_gains_personal_tools(tmp_path, allowed):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import agent_directory_service as directory
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            first = native.bootstrap(root)['assistant']
            directory.update_agent_instance(first['agentId'], tool_policy={'allowedTools': CUSTOM_TOOLS,
                'preferredTools': [], 'networkAccess': 'none', 'maxCallsPerTurn': 3})
            original = directory.get_agent(first['agentId'])['toolPolicy']
            assert native.shutdown()['closed']
            second = native.bootstrap(root)['assistant']
            assert second['directSessionId'] == first['directSessionId']
            assert directory.get_agent(second['agentId'])['toolPolicy'] == original
        finally:
            assert native.shutdown()['closed']
    """.replace('CUSTOM_TOOLS', repr(allowed)), config_text=TEST_MODEL_CONFIG)
