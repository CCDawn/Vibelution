"""Exercise the isolated activation boundary without operator state."""
import json

import pytest

from core.assistant_runtime.migration_io import MigrationIOError
from scripts.assistant_migration_activate import activate_in_subprocess, storage_authority
from scripts.assistant_migration_inventory import _bound_route
from tests.test_assistant_migration_cli import authorized_fixture, call
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_incremental_activation_requires_a_distinct_baseline_and_rejects_initial_admission():
    common = dict(paths=None, workspace=None, agent_id="old", source_config=None, target_profile=None,
                  target_config=None, migration_id="sync-one", path_grants=None,
                  authority_snapshots=(), authority_verify=lambda: None, category="knowledge_sync")
    for baseline, admission, reason in [(None, None, "knowledge_sync_baseline_invalid"),
                                        ("sync-one", None, "knowledge_sync_baseline_invalid"),
                                        ("initial-one", {}, "knowledge_sync_admission_unavailable")]:
        with pytest.raises(MigrationIOError, match=reason):
            activate_in_subprocess(**common, baseline_migration_id=baseline, initial_control=admission)


def test_isolated_activation_uses_original_baseline_and_publishes_increment(tmp_path, monkeypatch, capsys):
    workspace, source_paths = authorized_fixture(tmp_path, monkeypatch)
    (tmp_path / "source-location.json").write_text(json.dumps({"workspace": str(workspace)}), encoding="utf-8")
    _run(tmp_path, r'''
        import json, os, shutil
        from pathlib import Path
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import team_knowledge_service as s
        s._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = Path(json.loads((root.parent / 'source-location.json').read_text())['workspace'])
        with offline_migration_profile() as lease:
            old = lease.agent_id
            base = s.create_agent_knowledge_base(old, name='Fixture', actor_agent_id=old)
            entry = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='BASE_FIXTURE', title='Fixture', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, entry['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True, knowledge_base_id=base['scopedKnowledgeBaseId'],
                knowledge_content='BASE_FIXTURE')
            shutil.copytree(s._knowledge_root_for_owner(s._require_owner_context('agent', old)), workspace / 'agents' / old / 'knowledge')
            registry = workspace / 'knowledge/sources/registry'; registry.mkdir(parents=True)
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
            row = {'agentId': old, 'directSessionId': lease.session_id, 'status': 'active',
                'roleKey': 'personal_assistant', 'metadata': {'personalAssistantProfile': 'personal_assistant_v1'}}
            (workspace / 'agents/agents.json').write_text(json.dumps({'agents': [row]}), encoding='utf-8')
            (root.parent / 'old-id.txt').write_text(old, encoding='utf-8')
    ''', config_text=TEST_MODEL_CONFIG)
    old = (tmp_path / 'old-id.txt').read_text(encoding='utf-8')
    source_config = tmp_path / 'source-config.toml'
    source_config.write_text('[launcher.developer_mode]\nenabled=false\n', encoding='utf-8')
    target = tmp_path / 'new-profile' / 'native'
    config = target / 'config/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text(TEST_MODEL_CONFIG, encoding='utf-8')
    assert call(monkeypatch, '--activate-knowledge', old, '--source-config', source_config,
                '--target-profile', target, '--target-config', config, '--migration-id', 'baseline') == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'complete'
    _run(tmp_path, r'''
        import json, os, shutil
        from pathlib import Path
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import team_knowledge_service as s
        s._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        workspace = Path(json.loads((root.parent / 'source-location.json').read_text())['workspace'])
        with offline_migration_profile() as lease:
            old = lease.agent_id
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            entry = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='INCREMENT_FIXTURE', title='Fixture 2', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, entry['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True,
                knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']),
                knowledge_content='INCREMENT_FIXTURE')
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    paths, storage, verify_storage = storage_authority(source_paths.project_root, source_config)
    resolved, _, routing, verify_routing = _bound_route(paths, source_config)
    def verify():
        verify_storage(); verify_routing(); verify_storage()
    report = activate_in_subprocess(paths=paths, workspace=resolved, agent_id=old, source_config=source_config,
        target_profile=target, target_config=config, migration_id='sync-one', path_grants=None,
        authority_snapshots=(*storage, *routing), authority_verify=verify, category='knowledge_sync',
        baseline_migration_id='baseline')
    assert report['status'] == 'complete' and report['migrationId'] == 'sync-one'
    assert len(report['knowledge']['mappings']) == 1 and report['readyForCutover'] is False
    from core.assistant_runtime.knowledge_sync_receipt import read_knowledge_sync_receipt
    from core.assistant_runtime.migration_knowledge import verify_knowledge_completion
    baseline = verify_knowledge_completion(target, 'baseline')
    args = dict(sync_id='sync-one', baseline_id='baseline', source_scope=report['sourceScope'],
                target_agent_id=baseline['targetAgentId'])
    files = {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
    receipt = read_knowledge_sync_receipt(target, **args)
    assert receipt['state'] == 'completed' and receipt['plannedAppliedCount'] == 1
    assert receipt['pendingCount'] == receipt['skippedCount'] == 0
    assert read_knowledge_sync_receipt(target, **{**args, 'target_agent_id': 'different-owner'})['state'] == 'unknown'
    assert read_knowledge_sync_receipt(target, **{**args, 'sync_id': 'missing-id'})['state'] == 'unknown'
    assert files == {p: p.read_bytes() for p in target.rglob('*') if p.is_file()}
    from core.assistant_runtime.migration_knowledge import _digest
    path = target / 'knowledge_migrations/sync_operations' / (_digest('sync-one') + '.complete.json')
    original = path.read_bytes()
    path.write_text('{}', encoding='utf-8')
    assert read_knowledge_sync_receipt(target, **args)['state'] == 'unknown'
    path.write_bytes(original)


def test_read_only_receipt_never_continues_a_lost_batch_and_reports_terminal_skip(tmp_path):
    from tests.test_assistant_migration_knowledge import _create_isolated_source, _ISOLATED_SNAPSHOTS
    from tests.test_assistant_migration_knowledge_sync import _add_synthetic_source
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + "\n        with offline_migration_profile() as lease: run(lease)\n",
         config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'FIRST_FIXTURE')
    _add_synthetic_source(tmp_path, 'SECOND_FIXTURE')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            original = migration._import_one
            def interrupted(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(0)
            migration._import_one = interrupted
            sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='partial-fixture')
            raise AssertionError('expected process exit')
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'THIRD_FIXTURE')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        from core.assistant_runtime.knowledge_sync_receipt import read_knowledge_sync_receipt
        with offline_migration_profile() as lease:
            args = dict(sync_id='partial-fixture', baseline_id='workspace-bound',
                source_scope=resolved.report['sourceScope'], target_agent_id=lease.agent_id)
            before = contents(root / 'knowledge_migrations')
            assert read_knowledge_sync_receipt(root, **args)['state'] == 'unknown'
            assert contents(root / 'knowledge_migrations') == before
            # Explicit test recovery can finish the proven-unstarted suffix;
            # receipt read itself above did not execute it.
            result = sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='partial-fixture')
            assert result['skippedCount'] == 1 and result['pendingCount'] == 1
            before = contents(root / 'knowledge_migrations')
            receipt = read_knowledge_sync_receipt(root, **args)
            assert receipt['state'] == 'partial' and receipt['skippedCount'] == 1 and receipt['pendingCount'] == 1
            assert contents(root / 'knowledge_migrations') == before
            receipt_path = root / 'knowledge_migrations/sync_operations' / (migration._digest('partial-fixture') + '.complete.json')
            original_receipt = receipt_path.read_bytes()
            forged = json.loads(original_receipt); forged['terminalSha256'] = '0' * 64
            receipt_path.write_text(json.dumps(forged))
            assert read_knowledge_sync_receipt(root, **args)['state'] == 'unknown'
            receipt_path.write_bytes(original_receipt)
            terminal = root / 'knowledge_migrations/sync_items' / migration._digest('partial-fixture') / 'terminal.json'
            terminal.write_bytes(b'{}')
            assert read_knowledge_sync_receipt(root, **args)['state'] == 'unknown'
    ''', config_text=TEST_MODEL_CONFIG)
