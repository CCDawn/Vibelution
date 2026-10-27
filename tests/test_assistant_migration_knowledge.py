"""Synthetic native knowledge migration; never uses operator data or a model."""
import pytest

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


_ISOLATED_IMPORTS = r'''
        import hashlib, json, os, shutil, sys
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
        from core.infrastructure import developer_sandbox as sandbox
        s._extended_fs_path = lambda path: Path(path).resolve()
        # Preserve the strict lexical write audit for short temporary paths.
        sandbox._filesystem_path = lambda path: Path(path).resolve()
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        config_path = Path(directory.CONFIG_PATH)
        config_before = config_path.read_bytes()
'''

_ISOLATED_SOURCE = _ISOLATED_IMPORTS + r'''
        with offline_migration_profile() as source_lease:
            old = directory.create_agent_instance(display_name='Synthetic legacy owner')['agentId']
            base = s.create_agent_knowledge_base(old, name='Synthetic source', actor_agent_id=old)
            source = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='SYNTHETIC_APPROVED', title='Synthetic', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, source['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True, knowledge_base_id=base['scopedKnowledgeBaseId'],
                knowledge_content='SYNTHETIC_APPROVED')
            workspace = root.parent / 'legacy-workspace'
            private = workspace / 'agents' / old / 'knowledge'
            shutil.copytree(s._knowledge_root_for_owner(s._require_owner_context('agent', old)), private)
            registry = workspace / 'knowledge/sources/registry'
            registry.mkdir(parents=True)
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
        (root.parent / 'source-identity.json').write_text(json.dumps({'agentId': old}))
'''

_ISOLATED_SNAPSHOTS = _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-case/source-identity.json').read_text())['agentId']
        workspace = root.parent / 'source-case/legacy-workspace'
        private = workspace / 'agents' / old / 'knowledge'
        registry = workspace / 'knowledge/sources/registry'
        tree = fingerprint_tree(private)
        resolved = SourcePaths({'stage': 'source_snapshot', 'sourceScope': {
            'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': old},
            'sources': [{'sourceRef': 'private', 'category': 'private_knowledge', 'status': 'available',
                'entries': [{'path': v.path.relative_to(private).as_posix(), 'sha256': v.sha256,
                    'size': len(v.raw)} for v in tree]}]}, {'private': private},
            snapshots={'private': tuple(tree)}, directoryproofs={'private': tree.directories})
        central = read_stable_file(registry / 'source_registry.jsonl', 4*1024*1024)
        refs = read_stable_file(registry / 'owner_refs.jsonl', 4*1024*1024)
        def run(lease, authority_verify=None):
            return migration.import_private_knowledge(lease, resolved, central=central,
                owner_refs=refs, migration_id='workspace-bound', authority_verify=authority_verify)
        def fails(code, call):
            try:
                call()
            except MigrationIOError as error:
                assert str(error) == code, str(error)
            else:
                raise AssertionError('invalid import admitted: ' + code)
        def contents(path):
            return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in path.rglob('*') if p.is_file()} if path.exists() else {}
'''


def _create_isolated_source(tmp_path):
    source_case = tmp_path / 'source-case'
    source_case.mkdir()
    _run(source_case, _ISOLATED_SOURCE, config_text=TEST_MODEL_CONFIG)


def _create_revision_source(tmp_path, *, state='active'):
    source_case = tmp_path / 'source-case'
    source_case.mkdir()
    revision = r'''
            owner = s._require_owner_context('agent', old)
            original = s._read_jsonl(s._items_path_for_owner(owner))[0]
            latest = original
            for version in (2, 3):
                proposal = s.create_refinement_proposal(base['scopedKnowledgeBaseId'],
                    source_artifact_ids=latest['sourceArtifactIds'], proposed_by_agent_id=old,
                    title='Synthetic revision', content='SYNTHETIC_REVISION_' + str(version),
                    supersedes_knowledge_item_id=latest['knowledgeItemId'],
                    expected_content_sha256=latest['contentSha256'], revision_reason='Synthetic correction')
                latest = s.review_refinement_proposal(base['scopedKnowledgeBaseId'], proposal['proposalId'],
                    status='approved', reviewed_by_agent_id=old)['item']
            # A later pending or rejected proposal must never become knowledge.
            pending = s.create_refinement_proposal(base['scopedKnowledgeBaseId'],
                source_artifact_ids=latest['sourceArtifactIds'], proposed_by_agent_id=old,
                title='Synthetic pending', content='SYNTHETIC_UNAPPROVED',
                supersedes_knowledge_item_id=latest['knowledgeItemId'],
                expected_content_sha256=latest['contentSha256'], revision_reason='Not approved')
            rejected = s.create_refinement_proposal(base['scopedKnowledgeBaseId'],
                source_artifact_ids=latest['sourceArtifactIds'], proposed_by_agent_id=old,
                title='Synthetic rejected', content='SYNTHETIC_REJECTED')
            s.review_refinement_proposal(base['scopedKnowledgeBaseId'], rejected['proposalId'],
                status='rejected', reviewed_by_agent_id=old)
            state = STATE
            if state != 'active':
                s.set_knowledge_source_lifecycle(base['scopedKnowledgeBaseId'], latest['sourceArtifactIds'][0],
                    status='withdrawn' if state == 'withdrawn' else 'active', reason='Synthetic lifecycle',
                    actor_agent_id=old, expires_at={'expired': '2020-01-01T00:00:00Z',
                        'future': '2099-01-01T00:00:00Z'}.get(state, ''))
'''.replace('STATE', repr(state))
    _run(source_case, _ISOLATED_SOURCE.replace("            workspace = root.parent / 'legacy-workspace'",
        revision + "            workspace = root.parent / 'legacy-workspace'"), config_text=TEST_MODEL_CONFIG)


def test_native_governed_revision_import_survives_restart_without_replaying_review(tmp_path):
    _create_revision_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            original_write = migration._write_state
            def lost_ack(path, state):
                if state['phase'] == 'published':
                    raise RuntimeError('Synthetic lost acknowledgement')
                return original_write(path, state)
            migration._write_state = lost_ack
            fails('knowledge_native_operation_unavailable', lambda: run(lease))
            migration._write_state = original_write
            result = run(lease)
            assert result['importedCount'] == 1 and len(result['mappings']) == 1, result
            items = [json.loads(line) for line in (private / 'items.jsonl').read_bytes().splitlines()]
            assert result['mappings'][0]['sourceKnowledgeItemId'] == items[-1]['knowledgeItemId']
            assert [v['reason'] for v in result['excluded']] == ['superseded', 'superseded']
            assert not result['readyForCutover'] and not result['sourceQuiesced']
            (root.parent / 'revision-result.json').write_text(json.dumps(result))
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from tools.team_knowledge_tools import search_agent_private_memory_tool
        with offline_migration_profile() as lease:
            before = contents(s._knowledge_root_for_owner(s._require_owner_context('agent', lease.agent_id)))
            s.review_owner_inbox_source = lambda *a, **k: (_ for _ in ()).throw(AssertionError('review replayed'))
            result = run(lease)
            assert result['idempotent'] and result['importedCount'] == 0
            assert result['mappings'] == json.loads((root.parent / 'revision-result.json').read_text())['mappings']
            owner = s._require_owner_context('agent', lease.agent_id)
            assert contents(s._knowledge_root_for_owner(owner)) == before
            assert len(s._read_jsonl(s._items_path_for_owner(owner))) == 1
            with directory.active_agent_runtime(lease.agent_id, session_id=lease.session_id, turn_id='revision-search'):
                found = json.loads(search_agent_private_memory_tool(query='SYNTHETIC_REVISION_3', query_mode='exact'))
                assert found['ok'] and found['results'], found
                for text in ('SYNTHETIC_APPROVED', 'SYNTHETIC_REVISION_2', 'SYNTHETIC_UNAPPROVED', 'SYNTHETIC_REJECTED'):
                    found = json.loads(search_agent_private_memory_tool(query=text, query_mode='exact'))
                    assert found['ok'] and not found['results'], found
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('fault', ['missing_proposal', 'missing_review_receipt', 'missing_batch_receipt',
    'wrong_status', 'wrong_batch', 'parent_hash', 'missing_parent', 'root', 'branch', 'reviewer',
    'source_revision', 'required_reviewer', 'parent_content'])
def test_governed_revision_incomplete_proof_fails_before_target_writes(tmp_path, fault):
    _create_revision_source(tmp_path)
    tamper = r'''
        fault = FAULT
        def rows(name):
            return [json.loads(line) for line in (private / name).read_bytes().splitlines()]
        def write(name, values):
            (private / name).write_text(''.join(json.dumps(v) + '\n' for v in values))
        proposals = rows('refinement_proposals.jsonl')
        items = rows('items.jsonl')
        if fault == 'missing_proposal':
            proposals.pop(0)
        elif fault in {'missing_review_receipt', 'missing_batch_receipt'}:
            action = 'knowledge.proposal.reviewed' if fault == 'missing_review_receipt' else 'knowledge.batch.applied'
            audit = rows('audit.jsonl')
            victim = next(v for v in audit if v['action'] == action)
            write('audit.jsonl', [v for v in audit if v != victim])
        elif fault == 'wrong_status':
            proposals[0]['status'] = 'pending'
        elif fault == 'wrong_batch':
            proposals[0]['batchId'] = 'foreign-batch'
        elif fault == 'parent_hash':
            proposals[0]['expectedContentSha256'] = '0' * 64
        elif fault == 'missing_parent':
            items.pop(0)
        elif fault == 'root':
            items[-1]['rootKnowledgeItemId'] = 'foreign-root'
        elif fault == 'branch':
            items.append({**items[-1], 'knowledgeItemId': 'synthetic-fork'})
        elif fault == 'reviewer':
            proposals[0]['reviewedByAgentId'] = 'foreign-reviewer'
        elif fault == 'source_revision':
            items[0]['sourceLifecycleRevisions'] = {items[0]['sourceArtifactIds'][0]: 9}
        elif fault == 'required_reviewer':
            proposals[0]['requiredReviewerAgentId'] = old
        elif fault == 'parent_content':
            items[0]['content'] = 'Synthetic changed parent'
        write('items.jsonl', items)
        write('refinement_proposals.jsonl', proposals)
'''.replace('FAULT', repr(fault))
    _run(tmp_path, _ISOLATED_SNAPSHOTS.replace('        tree = fingerprint_tree(private)',
        tamper + '        tree = fingerprint_tree(private)') + r'''
        with offline_migration_profile() as lease:
            try:
                run(lease)
            except MigrationIOError as error:
                assert str(error) in {'knowledge_revision_chain_unsupported',
                    'knowledge_source_lineage_unprovable', 'knowledge_proposal_lineage_unprovable'}, error
            else:
                raise AssertionError('Invalid revision proof admitted')
            owner = s._require_owner_context('agent', lease.agent_id)
            assert not s._knowledge_bases_for_owner(owner)
            assert not s._read_jsonl(s._items_path_for_owner(owner))
            assert not (root / 'knowledge_migrations').exists()
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('operation', ['create', 'collect'])
@pytest.mark.parametrize('authority', ['config', 'active'])
@pytest.mark.parametrize('mutation', ['write', 'replace'])
def test_native_knowledge_pins_routing_authorities_during_native_call(tmp_path, operation, authority, mutation):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + '        operation, authority, mutation = ' + repr((operation, authority, mutation)) + '\n' + r'''
        active = sandbox._active_state_path(root)
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(json.dumps({'schemaVersion': 1, 'sandboxId': 'synthetic-existing'}))
        active_before = active.read_bytes()
        with offline_migration_profile() as lease:
            path = config_path if authority == 'config' else active
            original = s.create_agent_knowledge_base if operation == 'create' else s.collect_source_to_inbox
            observed = []
            def during_native(*args, **kwargs):
                try:
                    if mutation == 'write':
                        path.write_bytes(path.read_bytes() + b'\n')
                    else:
                        replacement = path.with_name('synthetic-replacement.tmp')
                        replacement.write_bytes(path.read_bytes())
                        try:
                            replacement.replace(path)
                        finally:
                            replacement.unlink(missing_ok=True)
                except PermissionError:
                    observed.append('blocked')
                else:
                    raise AssertionError('Routing authority mutation was allowed inside native API')
                return original(*args, **kwargs)
            if operation == 'create':
                s.create_agent_knowledge_base = during_native
            else:
                s.collect_source_to_inbox = during_native
            result = run(lease)
            assert result['importedCount'] == 1 and observed == ['blocked']
            assert config_path.read_bytes() == config_before and active.read_bytes() == active_before
    ''', config_text=TEST_MODEL_CONFIG)



@pytest.mark.parametrize('state', ['withdrawn', 'expired', 'future'])
def test_governed_revision_source_lifecycle_never_reactivates_ancestors(tmp_path, state):
    _create_revision_source(tmp_path, state=state)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + '        state = ' + repr(state) + '\n' + r'''
        with offline_migration_profile() as lease:
            if state == 'future':
                fails('knowledge_source_expiry_unsupported', lambda: run(lease))
            else:
                result = run(lease)
                assert result['importedCount'] == 0 and not result['mappings']
                assert [v['reason'] for v in result['excluded']] == ['superseded', 'superseded',
                    'source_withdrawn' if state == 'withdrawn' else 'source_expired']
            owner = s._require_owner_context('agent', lease.agent_id)
            assert not s._knowledge_bases_for_owner(owner)
            assert not s._read_jsonl(s._items_path_for_owner(owner))
    ''', config_text=TEST_MODEL_CONFIG)


def test_developer_mode_refuses_native_promotion_before_any_import_write(tmp_path):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        formal = sandbox.formal_workspace_path(root)
        before = contents(formal)
        with offline_migration_profile() as lease:
            owner = s._require_owner_context('agent', lease.agent_id)
            target = s._knowledge_root_for_owner(owner)
            assert target != formal / 'agents' / lease.agent_id / 'knowledge'
            target_before = contents(target)
            for attempt in range(2):
                fails('knowledge_native_promotion_blocked', lambda: run(lease))
                assert contents(target) == target_before
                assert not (root / 'knowledge_migrations').exists()
            assert contents(formal) == before
        # Restart preserves the sandbox identity and the same fail-closed policy.
        with offline_migration_profile() as lease:
            assert s._knowledge_root_for_owner(s._require_owner_context('agent', lease.agent_id)) == target
            fails('knowledge_native_promotion_blocked', lambda: run(lease))
            assert contents(target) == target_before
            assert contents(formal) == before
    ''', config_text=TEST_MODEL_CONFIG + '\n[launcher.developer_mode]\nenabled = true\n')


def test_developer_mode_with_only_withdrawn_source_never_seeds_formal_knowledge(tmp_path):
    import json
    _create_isolated_source(tmp_path)
    source = tmp_path / 'source-case'
    old = json.loads((source / 'source-identity.json').read_text(encoding='utf-8'))['agentId']
    artifacts = source / 'legacy-workspace' / 'agents' / old / 'knowledge/source_artifacts.jsonl'
    rows = [json.loads(line) for line in artifacts.read_text(encoding='utf-8').splitlines()]
    rows[0]['status'] = 'withdrawn'
    artifacts.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        formal = sandbox.formal_workspace_path(root)
        sentinel = formal / 'knowledge/private-formal-sentinel.txt'
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text('SYNTHETIC_FORMAL_ONLY')
        with offline_migration_profile() as lease:
            workspace = sandbox.sandboxed_workspace_path(root)
            before_formal = contents(formal)
            before_target = contents(workspace / 'knowledge')
            fails('knowledge_native_promotion_blocked', lambda: run(lease))
            assert contents(formal) == before_formal
            assert contents(workspace / 'knowledge') == before_target
            assert not list(workspace.rglob('private-formal-sentinel.txt'))
            assert not (root / 'knowledge_migrations').exists()
    ''', config_text=TEST_MODEL_CONFIG + '\n[launcher.developer_mode]\nenabled = true\n')


@pytest.mark.parametrize('phase', ['base_intent', 'collect_intent', 'review_intent', 'published'])
@pytest.mark.parametrize('change', ['enable', 'rewrite_same_bytes', 'authority'])
def test_routing_change_at_native_boundary_fails_closed(tmp_path, phase, change):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + '        phase, change = ' + repr((phase, change)) + '\n' + r'''
        with offline_migration_profile() as lease:
            owner = s._require_owner_context('agent', lease.agent_id)
            def counts():
                return (len(s._knowledge_bases_for_owner(owner)),
                    len(s._read_jsonl(s._owner_source_index_path(owner))),
                    len(s._read_jsonl(s._items_path_for_owner(owner))))
            original = migration._write_state
            observed = []
            denied = []
            def authority_verify():
                if denied:
                    raise MigrationIOError('trusted_source_authority_changed')
            def change_route(path, state):
                original(path, state)
                if state['phase'] == phase:
                    observed.append(counts())
                    if change == 'authority':
                        denied.append(True)
                    else:
                        try:
                            config_path.write_bytes(config_before + (b'\n[launcher.developer_mode]\nenabled = true\n'
                                if change == 'enable' else b''))
                        except PermissionError:
                            assert config_path.read_bytes() == config_before
                            raise MigrationIOError('knowledge_workspace_changed')
            migration._write_state = change_route
            try:
                fails('trusted_source_authority_changed' if change == 'authority' else 'knowledge_workspace_changed',
                    lambda: run(lease, authority_verify=authority_verify))
            finally:
                migration._write_state = original
                config_path.write_bytes(config_before)
            assert observed == [{'base_intent': (0, 0, 0), 'collect_intent': (1, 0, 0),
                'review_intent': (1, 1, 0), 'published': (1, 1, 1)}[phase]], observed
            assert counts() == observed[0]
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('identity', ['agent_workspace', 'private_path', 'central_path'])
def test_target_identity_mismatch_refuses_before_import_writes(tmp_path, identity):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + '        identity = ' + repr(identity) + '\n' + r'''
        with offline_migration_profile() as lease:
            before = contents(sandbox.formal_workspace_path(root))
            if identity == 'agent_workspace':
                original = directory.get_agent
                directory.get_agent = lambda *args, **kwargs: {**original(*args, **kwargs),
                    'workspacePath': 'workspace/agents/another-agent'}
            elif identity == 'private_path':
                s._knowledge_root_for_owner = lambda owner: root / 'workspace/agents/another-agent/knowledge'
            else:
                s._central_source_registry_path = lambda: root / 'workspace/knowledge/foreign-registry.jsonl'
            fails('knowledge_target_binding_invalid', lambda: run(lease))
            assert not (root / 'knowledge_migrations').exists()
            assert contents(sandbox.formal_workspace_path(root)) == before
    ''', config_text=TEST_MODEL_CONFIG)


def test_native_knowledge_restart_keeps_mapping_and_single_import(tmp_path):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            result = run(lease)
            assert result['importedCount'] == 1
            assert not result['sourceQuiesced'] and not result['readyForCutover']
            (root.parent / 'import-result.json').write_text(json.dumps(result))
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from tools.team_knowledge_tools import search_agent_private_memory_tool
        previous = json.loads((root.parent / 'import-result.json').read_text())
        with offline_migration_profile() as lease:
            result = run(lease)
            assert result['idempotent'] and result['importedCount'] == 0
            assert result['mappings'] == previous['mappings']
            assert result['targetAgentId'] == previous['targetAgentId'] == lease.agent_id
            owner = s._require_owner_context('agent', lease.agent_id)
            assert len(s._knowledge_bases_for_owner(owner)) == 1
            assert len(s._read_jsonl(s._owner_source_index_path(owner))) == 1
            assert len(s._read_jsonl(s._items_path_for_owner(owner))) == 1
            with directory.active_agent_runtime(lease.agent_id, session_id=lease.session_id, turn_id='restart-search'):
                found = json.loads(search_agent_private_memory_tool(query='SYNTHETIC_APPROVED', query_mode='exact'))
                assert found['ok'] and found['results'], found
    ''', config_text=TEST_MODEL_CONFIG)


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
