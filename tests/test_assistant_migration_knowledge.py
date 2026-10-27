"""Synthetic native knowledge migration; never uses operator data or a model."""
import pytest

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_native_private_knowledge_migration_and_crash_safety(tmp_path):
    _run(tmp_path, r'''
        import json, os, shutil, sys
        from pathlib import Path
        def no_network(event, args):
            if event == 'socket.connect':
                raise AssertionError('network forbidden')
        sys.addaudithook(no_network)
        from core.assistant_runtime import migration_knowledge as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_paths import SourcePaths
        from core.assistant_runtime.migration_io import fingerprint_tree, read_stable_file, MigrationIOError
        from core.web.services import team_knowledge_service as knowledge, agent_directory_service as directory
        from tools.team_knowledge_tools import search_agent_private_memory_tool
        # _run's audit compares lexical Path prefixes and does not normalize
        # Win32 extended spelling. These short temporary paths need no prefix;
        # all actual file writes still pass its unchanged containment audit.
        knowledge._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        def fails(code, call):
            try:
                call()
            except MigrationIOError as error:
                assert str(error) == code, str(error)
            else:
                raise AssertionError('accepted: ' + code)
        with offline_migration_profile() as lease:
            old = directory.create_agent_instance(display_name='Synthetic old PA', role_key='personal_assistant',
                metadata={'personalAssistantProfile': 'personal_assistant_v1'})['agentId']
            stranger = directory.create_agent_instance(display_name='Synthetic outsider')['agentId']
            base = knowledge.create_agent_knowledge_base(old, name='Old private', actor_agent_id=old)
            def make(text, accept=True):
                source = knowledge.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                    original_content=text, title=text, source_ref={'note': 'synthetic'}, actor_agent_id=old)
                if not accept:
                    return source
                return knowledge.review_owner_inbox_source('agent', old, source['inboxSourceId'],
                    decision='accepted', reviewed_by_agent_id=old, ingest_on_accept=True,
                    knowledge_base_id=base['scopedKnowledgeBaseId'], knowledge_content=text)
            approved = make('SYNTHETIC_APPROVED_SECRET')
            withdrawn = make('SYNTHETIC_WITHDRAWN_SECRET')
            knowledge.set_knowledge_source_lifecycle(base['scopedKnowledgeBaseId'],
                withdrawn['directIngestion']['sourceArtifact']['sourceArtifactId'],
                status='withdrawn', reason='synthetic withdrawal', actor_agent_id=old)
            make('SYNTHETIC_PENDING_SECRET', False)
            workspace = root.parent / 'legacy-workspace'
            source_root = workspace / 'agents' / old / 'knowledge'
            old_owner = knowledge._require_owner_context('agent', old)
            shutil.copytree(knowledge._knowledge_root_for_owner(old_owner), source_root)
            registry = workspace / 'knowledge/sources/registry'
            registry.mkdir(parents=True)
            shutil.copyfile(knowledge._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(knowledge._central_owner_refs_path(), registry / 'owner_refs.jsonl')
            tree = fingerprint_tree(source_root)
            scope = {'projectId': 'synthetic-old-project', 'instanceId': 'synthetic-old-instance', 'agentId': old}
            resolved = SourcePaths({'schemaVersion': 1, 'stage': 'source_snapshot', 'sourceScope': scope,
                'sources': [{'sourceRef': 'old-private', 'category': 'private_knowledge', 'status': 'available',
                    'entries': [{'path': s.path.relative_to(source_root).as_posix(), 'sha256': s.sha256,
                        'size': len(s.raw)} for s in tree]}]}, {'old-private': source_root},
                snapshots={'old-private': tuple(tree)}, directoryproofs={'old-private': tree.directories})
            central = read_stable_file(registry / 'source_registry.jsonl', 4*1024*1024)
            refs = read_stable_file(registry / 'owner_refs.jsonl', 4*1024*1024)
            def run(mid='knowledge-one'):
                return migration.import_private_knowledge(lease, resolved, central=central,
                    owner_refs=refs, migration_id=mid)
            # Lose the ACK after the complete native direct review. Its state
            # remains review_intent, so retry must read the same native IDs.
            original = migration._write_state
            def crash(path, state):
                if state.get('phase') == 'published':
                    raise RuntimeError('SYNTHETIC_SECRET_LOST_ACK')
                return original(path, state)
            migration._write_state = crash
            fails('knowledge_native_operation_unavailable', run)
            migration._write_state = original
            result = run()
            assert result['importedCount'] == 1 and len(result['mappings']) == 1, result
            assert result['readyForCutover'] is False and result['sourceQuiesced'] is False
            assert 'SECRET' not in json.dumps(result)
            assert result['mappings'][0]['sourceKnowledgeItemId'] == approved['directIngestion']['item']['knowledgeItemId']
            with directory.active_agent_runtime(lease.agent_id, session_id=lease.session_id, turn_id='search-import'):
                found = json.loads(search_agent_private_memory_tool(query='SYNTHETIC_APPROVED_SECRET', query_mode='exact'))
                assert found['ok'] and found['results'], found
                assert 'SYNTHETIC_WITHDRAWN_SECRET' not in json.dumps(found)
                assert 'SYNTHETIC_PENDING_SECRET' not in json.dumps(found)
            target = knowledge.list_agent_knowledge_bases(lease.agent_id, actor_agent_id=lease.agent_id)
            assert target['summary']['knowledgeBaseCount'] == 1
            assert not knowledge.list_agent_knowledge_bases(lease.agent_id, actor_agent_id=stranger)['knowledgeBases']
            assert run()['idempotent']
            assert knowledge.list_agent_knowledge_bases(lease.agent_id, actor_agent_id=lease.agent_id)['summary']['knowledgeBaseCount'] == 1
            # New migration IDs still bind the same origin to the existing mapping.
            assert run('same-origin')['idempotent']
            target_owner = knowledge._require_owner_context('agent', lease.agent_id)
            assert len(knowledge._read_jsonl(knowledge._items_path_for_owner(target_owner))) == 1
            assert len(knowledge._read_jsonl(knowledge._owner_source_index_path(target_owner))) == 1
            # Stable snapshots are checked even on retries, before any write.
            items_path = source_root / 'items.jsonl'
            before = items_path.read_bytes()
            items_path.write_bytes(before + b'\n')
            fails('source_changed', run)
            assert knowledge.list_agent_knowledge_bases(lease.agent_id, actor_agent_id=lease.agent_id)['summary']['knowledgeBaseCount'] == 1
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("stage", ["base_after", "collect_after", "collect_before", "review_before", "item_after", "source_acl",
    "missing_owner_ref", "revision_chain", "future_expiry", "expired", "foreign_owner", "target_corrupt"])
def test_native_unknown_outcome_never_repeats_create_or_review(tmp_path, stage):
    _run(tmp_path, '        stage = ' + repr(stage) + '\n' + r'''
        import json, os, shutil, sys
        from pathlib import Path
        def no_network(event, args):
            if event == 'socket.connect':
                raise AssertionError('network forbidden')
        sys.addaudithook(no_network)
        from core.assistant_runtime import migration_knowledge as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_paths import SourcePaths
        from core.assistant_runtime.migration_io import fingerprint_tree, read_stable_file, MigrationIOError
        from core.web.services import team_knowledge_service as s, agent_directory_service as directory
        s._extended_fs_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        with offline_migration_profile() as lease:
            old = directory.create_agent_instance(display_name='Synthetic old PA', role_key='personal_assistant',
                metadata={'personalAssistantProfile': 'personal_assistant_v1'})['agentId']
            base = s.create_agent_knowledge_base(old, name='Synthetic source', actor_agent_id=old)
            source = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='SYNTHETIC_SECRET', title='Synthetic', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, source['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True, knowledge_base_id=base['scopedKnowledgeBaseId'],
                knowledge_content='SYNTHETIC_SECRET')
            workspace = root.parent / 'old-workspace'
            private = workspace / 'agents' / old / 'knowledge'
            shutil.copytree(s._knowledge_root_for_owner(s._require_owner_context('agent', old)), private)
            registry = workspace / 'knowledge/sources/registry'
            registry.mkdir(parents=True)
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
            if stage == 'source_acl':
                path = private / 'knowledge_bases.json'
                payload = json.loads(path.read_bytes())
                payload['knowledgeBases'][0]['acl']['grants']['read'] = ['synthetic-other-agent']
                path.write_text(json.dumps(payload))
            elif stage == 'missing_owner_ref':
                (registry / 'owner_refs.jsonl').write_bytes(b'')
            elif stage in {'revision_chain', 'foreign_owner'}:
                path = private / 'items.jsonl'
                rows = [json.loads(line) for line in path.read_bytes().splitlines()]
                rows[0].update({'revision': 2} if stage == 'revision_chain' else {'ownerId': 'other-agent'})
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            elif stage in {'future_expiry', 'expired'}:
                path = private / 'source_artifacts.jsonl'
                rows = [json.loads(line) for line in path.read_bytes().splitlines()]
                rows[0]['expiresAt'] = '2099-01-01T00:00:00Z' if stage == 'future_expiry' else '2020-01-01T00:00:00Z'
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            tree = fingerprint_tree(private)
            resolved = SourcePaths({'stage': 'source_snapshot', 'sourceScope': {'projectId': 'old-project',
                'instanceId': 'old-instance', 'agentId': old}, 'sources': [{'sourceRef': 'private',
                'category': 'private_knowledge', 'status': 'available', 'entries': [
                    {'path': v.path.relative_to(private).as_posix(), 'sha256': v.sha256, 'size': len(v.raw)} for v in tree]}]},
                {'private': private}, snapshots={'private': tuple(tree)}, directoryproofs={'private': tree.directories})
            def run():
                return migration.import_private_knowledge(lease, resolved,
                    central=read_stable_file(registry / 'source_registry.jsonl', 4*1024*1024),
                    owner_refs=read_stable_file(registry / 'owner_refs.jsonl', 4*1024*1024), migration_id='crash')
            owner = s._require_owner_context('agent', lease.agent_id)
            if stage == 'target_corrupt':
                path = s._knowledge_bases_path_for_owner(owner)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{"PRIVATE_SECRET": bad-json}')
            expected = {'source_acl': 'knowledge_source_acl_unprovable',
                'missing_owner_ref': 'knowledge_source_lineage_unprovable',
                'revision_chain': 'knowledge_revision_chain_unsupported',
                'future_expiry': 'knowledge_source_expiry_unsupported',
                'foreign_owner': 'knowledge_foreign_source_owner', 'target_corrupt': 'invalid_source_json'}
            if stage in expected:
                try:
                    run()
                except MigrationIOError as error:
                    assert str(error) == expected[stage], str(error)
                else:
                    raise AssertionError('unprovable import admitted')
                assert not s._read_jsonl(s._items_path_for_owner(owner))
                assert not s._knowledge_bases_for_owner(owner)
                raise SystemExit(0)
            if stage == 'expired':
                result = run()
                assert result['importedCount'] == 0 and result['excluded'][0]['reason'] == 'source_expired'
                assert not s._knowledge_bases_for_owner(owner)
                raise SystemExit(0)
            original_base, original_collect, original_review, original_append = s.create_agent_knowledge_base, s.collect_source_to_inbox, s.review_owner_inbox_source, s._append_jsonl
            def crash(*args, **kwargs):
                raise RuntimeError('SYNTHETIC_SECRET_FAULT')
            if stage == 'base_after':
                def base_then_crash(*args, **kwargs):
                    original_base(*args, **kwargs)
                    crash()
                s.create_agent_knowledge_base = base_then_crash
            elif stage == 'collect_after':
                def collect_then_crash(*args, **kwargs):
                    original_collect(*args, **kwargs)
                    crash()
                s.collect_source_to_inbox = collect_then_crash
            elif stage == 'collect_before':
                s.collect_source_to_inbox = crash
            elif stage == 'review_before':
                s.review_owner_inbox_source = crash
            else:
                def append_then_crash(path, row):
                    original_append(path, row)
                    if path == s._items_path_for_owner(owner):
                        crash()
                s._append_jsonl = append_then_crash
            try:
                run()
            except MigrationIOError as error:
                assert str(error) == 'knowledge_native_operation_unavailable', str(error)
            else:
                raise AssertionError('fault missed')
            s.create_agent_knowledge_base, s.collect_source_to_inbox, s.review_owner_inbox_source, s._append_jsonl = original_base, original_collect, original_review, original_append
            def counts():
                return (len(s._knowledge_bases_for_owner(owner)), len(s._read_jsonl(s._owner_source_index_path(owner))),
                    len(s._read_jsonl(s._items_path_for_owner(owner))))
            before = counts()
            if stage in {'base_after', 'collect_after'}:
                assert before == ((1, 0, 0) if stage == 'base_after' else (1, 1, 0)), before
                assert run()['importedCount'] == 1
                assert counts() == (1, 1, 1)
                assert run()['idempotent'] and counts() == (1, 1, 1)
                raise SystemExit(0)
            assert before == {'collect_before': (1, 0, 0), 'review_before': (1, 1, 0), 'item_after': (1, 1, 1)}[stage], before
            for retry in range(2):
                try:
                    run()
                except MigrationIOError as error:
                    assert str(error) == 'knowledge_outcome_unknown', str(error)
                else:
                    raise AssertionError('uncertain native operation replayed')
                assert counts() == before
    ''', config_text=TEST_MODEL_CONFIG)
