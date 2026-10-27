"""Selected source data reaches native PA activity without replay or cutover."""
import json
from pathlib import Path

from tests.test_assistant_migration_history import AGENT, source
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_authorized_personal_data_reaches_native_tools_and_survives_restart(tmp_path):
    workspace = source(tmp_path)
    events = workspace / 'agents' / AGENT / 'events/episodic_events.jsonl'
    events.parent.mkdir(parents=True)
    episodes = [
        {'schemaVersion': 1, 'episodeId': 'old-episode', 'eventId': 'old-episode', 'agentId': AGENT,
         'kind': 'preference', 'text': '旧的虚构偏好', 'refs': [], 'occurredAt': '2025-01-01T00:00:00+00:00',
         'validFrom': '2025-01-01T00:00:00+00:00', 'validUntil': '2025-01-02T00:00:00+00:00',
         'supersededByEpisodeId': 'new-episode'},
        {'schemaVersion': 1, 'episodeId': 'new-episode', 'eventId': 'new-episode', 'agentId': AGENT,
         'kind': 'preference', 'text': '当前虚构偏好', 'refs': [], 'occurredAt': '2025-01-02T00:00:00+00:00',
         'validFrom': '2025-01-02T00:00:00+00:00', 'validUntil': '', 'supersededByEpisodeId': ''},
    ]
    events.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in episodes), encoding='utf-8')
    ledger = workspace / 'agents' / AGENT / 'plugins/personal-affairs/affairs/items.jsonl'
    ledger.parent.mkdir(parents=True)
    affairs = [{'schemaVersion': 1, 'itemId': 'old-todo', 'kind': 'todo', 'title': '虚构任务',
                'note': '', 'status': 'open', 'dueAt': '', 'createdAt': '2025-01-01T00:00:00+00:00',
                'updatedAt': '2025-01-01T00:00:00+00:00', 'completedAt': '', 'sourceTurnId': 'old-turn'}]
    ledger.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in affairs), encoding='utf-8')
    before = {path: path.read_bytes() for path in workspace.rglob('*') if path.is_file()}
    case = {'workspace': str(workspace), 'project': str(workspace.parent), 'agent': AGENT}
    (tmp_path / 'migration-source.json').write_text(json.dumps(case), encoding='utf-8')
    code = '''
        import json, os, sys
        from pathlib import Path
        def no_network(event, args):
            if event == 'socket.connect': raise AssertionError('unexpected provider call')
        sys.addaudithook(no_network)
        from core.assistant_runtime.migration_active import activate_personal_snapshot
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
        from core.assistant_runtime.migration_io import read_stable_file, strict_json, verify_snapshot
        from core.assistant_runtime.migration_inventory import declared_assistant_identities
        from core.web.services import personal_affairs_service
        from core.web.services.agent_directory import episodic_memory
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        case = json.loads((root.parent / 'migration-source.json').read_text())
        workspace, project = Path(case['workspace']), Path(case['project'])
        registry = read_stable_file(workspace / 'agents/agents.json', 16 * 1024 * 1024)
        raw = strict_json(registry.raw)
        assert [r['agentId'] for r in declared_assistant_identities(raw['agents'])] == [case['agent']]
        with offline_migration_profile() as lease:
            resolved = source_snapshot(resolve_source_paths(project_root=project, workspace=workspace,
                project_id='project-1', instance_id='instance-1', agent_row=raw['agents'][0]))
            result = activate_personal_snapshot(lease, resolved, migration_id='active-1',
                source_roots=(project, workspace), authority_snapshots=(registry,),
                authority_verify=lambda: verify_snapshot(registry))
            assert result['status'] == 'complete' and not result['readyForCutover']
            assert not result['sourceQuiesced'] and result['archive']['published']
            if (root.parent / 'first-pass.json').exists():
                assert result['episodic']['idempotent'] and result['affairs']['idempotent']
            else:
                assert result['episodic']['importedCount'] == 2 and result['affairs']['importedCount'] == 1
            rows = episodic_memory.list_episodic_events(lease.agent_id, include_superseded=True)
            old = next(row for row in rows if row['episodeId'] == 'old-episode')
            assert old['supersededByEpisodeId'] == 'new-episode' and old['agentId'] == lease.agent_id
            service = personal_affairs_service.get_personal_affairs_service()
            item = next(row for row in service.list_items(lease.agent_id)['items'] if row['itemId'] == 'old-todo')
            if (root.parent / 'first-pass.json').exists():
                assert item['status'] == 'done'
            else:
                assert item['status'] == 'open'
                service.complete_item(lease.agent_id, item_id='old-todo')
                (root.parent / 'first-pass.json').write_text(json.dumps({'agentId': lease.agent_id}))
    '''
    _run(tmp_path, code, config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, code, config_text=TEST_MODEL_CONFIG)
    assert before == {path: path.read_bytes() for path in workspace.rglob('*') if path.is_file()}


def test_invalid_or_unauthorized_selection_never_creates_archive_or_active_data(tmp_path):
    workspace = source(tmp_path)
    (tmp_path / 'migration-source.json').write_text(json.dumps({'workspace': str(workspace),
        'project': str(workspace.parent), 'agent': AGENT}), encoding='utf-8')
    _run(tmp_path, '''
        import json, os
        from pathlib import Path
        from core.assistant_runtime.migration_active import activate_personal_snapshot
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_paths import resolve_source_paths, source_snapshot
        from core.assistant_runtime.migration_io import MigrationIOError
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        case = json.loads((root.parent / 'migration-source.json').read_text())
        workspace, project = Path(case['workspace']), Path(case['project'])
        raw = json.loads((workspace / 'agents/agents.json').read_text())
        with offline_migration_profile() as lease:
            captured = source_snapshot(resolve_source_paths(project_root=project, workspace=workspace,
                project_id='project-1', instance_id='instance-1', agent_row=raw['agents'][0]))
            try:
                activate_personal_snapshot(lease, captured, migration_id='missing',
                    source_roots=(project, workspace), authority_verify=lambda: None)
            except MigrationIOError:
                pass
            else:
                raise AssertionError('missing personal sources treated as an empty import')
            assert not (root / 'history_sources').exists()
            assert not (root / 'affairs_migrations').exists()
            assert not (root / 'episodic_migrations').exists()
    ''', config_text=TEST_MODEL_CONFIG)
