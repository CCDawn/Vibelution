"""Synthetic, isolated tests for conservative offline knowledge sync."""
import pytest

from tests.test_assistant_migration_knowledge import (
    _create_isolated_source, _ISOLATED_IMPORTS, _ISOLATED_SNAPSHOTS,
)
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def _add_synthetic_source(tmp_path, content):
    _run(tmp_path / 'source-case', '        added = ' + repr(content) + '\n' + _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-identity.json').read_text())['agentId']
        with offline_migration_profile():
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            source = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content=added, title=added, actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, source['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True,
                knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']),
                knowledge_content=added)
            workspace = root.parent / 'legacy-workspace'
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('legacy', [False, True])
def test_confirm_original_receipt_after_live_source_changes(tmp_path, legacy):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            run(lease)
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_FIRST')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            original = migration._immutable
            def lost_receipt(path, value):
                if path.parent.name == 'sync_operations' and path.name.endswith('.complete.json'):
                    os._exit(0)  # Real process exit after native writes, before the final receipt.
                return original(path, value)
            migration._immutable = lost_receipt
            sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='original-sync')
            raise AssertionError('lost receipt not observed')
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_LATER')
    _run(tmp_path, '        legacy = ' + repr(legacy) + '\n' + _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            if legacy:
                operations = root / 'knowledge_migrations/sync_operations'
                path = operations / (migration._digest('original-sync') + '.plan.json')
                plan = json.loads(path.read_bytes())
                plan['schemaVersion'] = 1
                path.write_text(json.dumps(plan))
            operations = root / 'knowledge_migrations/sync_operations'
            path = operations / (migration._digest('original-sync') + '.plan.json')
            plan = json.loads(path.read_bytes())
            archived = root / 'knowledge_migrations/archives' / plan['sourceProofSha256'] / 'private/items.jsonl'
            saved = archived.read_bytes()
            archived.write_bytes(saved + b'\n')
            fails('knowledge_sync_operation_conflict', lambda: sync('original-sync'))
            archived.write_bytes(saved)
            result = sync('original-sync')
            assert result['reused'] and len(result['mappings']) == 1
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 2 and all(item['content'] != 'SYNTHETIC_LATER' for item in items)
            fresh = sync('new-source-sync')
            assert len(fresh['mappings']) == 1 and fresh['conflictCount'] == 0
            assert len(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')) == 3
            operations = root / 'knowledge_migrations/sync_operations'
            stem = migration._digest('original-sync')
            plan_path = operations / (stem + '.plan.json')
            receipt_path = operations / (stem + '.complete.json')
            saved_plan, saved_receipt = plan_path.read_bytes(), receipt_path.read_bytes()
            for schema in (1, 2):
                plan, receipt = json.loads(saved_plan), json.loads(saved_receipt)
                plan['schemaVersion'] = schema
                receipt['planSha256'] = migration._digest(plan)
                plan_path.write_text(json.dumps(plan))
                receipt_path.write_text(json.dumps(receipt))
                assert sync('original-sync')['mappings'] == result['mappings']
            plan_path.write_bytes(saved_plan)
            receipt_path.write_bytes(saved_receipt)
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('exit_step', ['certificate', 'terminal'])
def test_changed_source_finalizes_completed_and_replans_unstarted_item(tmp_path, exit_step):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            run(lease)
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_FIRST')
    _add_synthetic_source(tmp_path, 'SYNTHETIC_SECOND')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            original = migration._import_one
            def lost_ack(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(0)  # Actual process termination after the first native import.
            migration._import_one = lost_ack
            sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='partial-source-change')
            raise AssertionError('lost acknowledgement not observed')
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_THIRD')
    _run(tmp_path, '        exit_step = ' + repr(exit_step) + '\n' + _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            original = migration._immutable
            def exit_after_terminal(path, value):
                if exit_step == 'certificate' and path.name.endswith('.not-started.json'):
                    original(path, value)
                    os._exit(0)  # Certificate persisted, terminal decision not yet written.
                if exit_step == 'terminal' and path.parent.name == 'sync_operations' and path.name.endswith('.complete.json'):
                    os._exit(0)  # Terminal decision is durable, final receipt is not.
                return original(path, value)
            migration._immutable = exit_after_terminal
            sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='partial-source-change')
            raise AssertionError('process exit not observed')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            # The initial import belongs to another knowledge root. A user
            # may edit it after the certificate or terminal was persisted.
            owner = s._require_owner_context('agent', lease.agent_id)
            initial = migration.verify_knowledge_completion(root, 'workspace-bound')['mappings'][0]
            s.update_knowledge_item_metadata(s._owner_scoped_knowledge_base_id(owner, initial['knowledgeBaseId']),
                initial['knowledgeItemId'], metadata_patch={'unrelated_user_edit': True}, actor_agent_id=lease.agent_id)
            result = sync('partial-source-change')
            assert result['reused'] and len(result['mappings']) == 1 and result['skippedCount'] == 1
            assert result['pendingCount'] == 1
            assert sync('partial-source-change') == result
            terminal = root / 'knowledge_migrations/sync_items' / migration._digest('partial-source-change') / 'terminal.json'
            saved = terminal.read_bytes()
            terminal.write_bytes(b'{}')
            fails('knowledge_sync_receipt_invalid', lambda: sync('partial-source-change'))
            fails('knowledge_sync_receipt_invalid', lambda: sync('another-id'))
            terminal.write_bytes(saved)
            partial_receipt = root / 'knowledge_migrations/sync_operations' / (migration._digest('partial-source-change') + '.complete.json')
            skipped = json.loads(partial_receipt.read_bytes())['skippedSourceKnowledgeItemIds']
            certificate = terminal.parent / (migration._digest(skipped[0]) + '.not-started.json')
            saved_certificate = certificate.read_bytes()
            certificate.write_bytes(b'{}')
            fails('knowledge_sync_receipt_invalid', lambda: sync('partial-source-change'))
            certificate.write_bytes(saved_certificate)
            attempted = terminal.parent / (migration._digest(skipped[0]) + '.intent.json')
            attempted.write_bytes(b'{}')
            fails('knowledge_sync_receipt_invalid', lambda: sync('partial-source-change'))
            attempted.unlink()
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 2 and all(item['content'] != 'SYNTHETIC_THIRD' for item in items)
            following = sync('another-id')
            assert len(following['mappings']) == 2 and following['skippedCount'] == 0 and following['conflictCount'] == 1
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 4 and any(row.get('metadata') == {'unrelated_user_edit': True} for row in items)
            # The old terminal remains valid after a different ID creates the skipped item.
            assert sync('partial-source-change') == result
            saved_terminal, saved_receipt = terminal.read_bytes(), partial_receipt.read_bytes()
            previous = json.loads(saved_terminal)
            legacy_terminal = {key: previous[key] for key in ('planSha256', 'completedCount', 'skippedSourceKnowledgeItemIds')}
            legacy_terminal['schemaVersion'] = 1
            legacy_receipt = json.loads(saved_receipt)
            legacy_receipt.pop('terminalSha256')
            certificate_lock = certificate.with_name(certificate.name + '.lock')
            saved_lock = certificate_lock.read_bytes()
            terminal.write_text(json.dumps(legacy_terminal))
            partial_receipt.write_text(json.dumps(legacy_receipt))
            fails('knowledge_sync_receipt_invalid', lambda: sync('partial-source-change'))
            certificate.unlink()
            certificate_lock.unlink()
            assert sync('partial-source-change') == result
            terminal.write_bytes(saved_terminal)
            partial_receipt.write_bytes(saved_receipt)
            certificate.write_bytes(saved_certificate)
            certificate_lock.write_bytes(saved_lock)
    ''', config_text=TEST_MODEL_CONFIG)


def test_process_exit_after_one_item_resumes_only_unstarted_item(tmp_path):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            run(lease)
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_FIRST')
    _add_synthetic_source(tmp_path, 'SYNTHETIC_SECOND')
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            original = migration._import_one
            def exit_after_first(*args, **kwargs):
                original(*args, **kwargs)
                os._exit(0)  # Bypass context cleanup and process finally blocks.
            migration._import_one = exit_after_first
            sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='interrupted-batch')
            raise AssertionError('process exit not observed')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            result = sync('interrupted-batch')
            assert result['reused'] and len(result['mappings']) == 2
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 3
            assert sum(row['content'] == 'SYNTHETIC_FIRST' for row in items) == 1
            assert sum(row['content'] == 'SYNTHETIC_SECOND' for row in items) == 1
            assert sync('following-batch')['mappings'] == []
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('has_execution_trace', [False, True, 'orphan_audit'])
def test_missing_progress_recovers_only_if_no_execution_trace(tmp_path, has_execution_trace):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            run(lease)
    ''', config_text=TEST_MODEL_CONFIG)
    _add_synthetic_source(tmp_path, 'SYNTHETIC_NEW')
    _run(tmp_path, '        has_execution_trace = ' + repr(has_execution_trace) + '\n' + _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime import migration_knowledge_sync as sync_module
        with offline_migration_profile() as lease:
            if has_execution_trace is True:
                def exit_after_intent(*args, **kwargs):
                    os._exit(0)
                migration._import_one = exit_after_intent
            else:
                def exit_before_progress(*args, **kwargs):
                    os._exit(0)
                sync_module._execute_plan = exit_before_progress
            sync_module.sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='missing-progress')
            raise AssertionError('process exit not observed')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, '        has_execution_trace = ' + repr(has_execution_trace) + '\n' + _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            if has_execution_trace is True:
                progress = root / 'knowledge_migrations/sync_items' / migration._digest('missing-progress') / 'progress.json'
                progress.unlink()
                fails('knowledge_sync_outcome_unknown', lambda: sync('missing-progress'))
                fails('knowledge_sync_prior_outcome_unknown', lambda: sync('other-id'))
            elif has_execution_trace == 'orphan_audit':
                owner = s._require_owner_context('agent', lease.agent_id)
                s._append_audit(owner, 'knowledge_base.created', {'knowledgeBaseId': 'missing-base'},
                    actor_agent_id=lease.agent_id)
                fails('knowledge_sync_outcome_unknown', lambda: sync('missing-progress'))
                fails('knowledge_sync_prior_outcome_unknown', lambda: sync('other-id'))
            else:
                result = sync('missing-progress')
                assert result['reused'] and len(result['mappings']) == 1
                owner = s._require_owner_context('agent', lease.agent_id)
                items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
                assert len(items) == 2 and sum(row['content'] == 'SYNTHETIC_NEW' for row in items) == 1
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize('partial', ['none', 'recoverable', 'unknown', 'edited', 'no_intent'])
def test_offline_sync_imports_new_root_once_and_preserves_target_edits(tmp_path, partial):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            result = run(lease)
            mapping = result['mappings'][0]
            owner = s._require_owner_context('agent', lease.agent_id)
            s.update_knowledge_item_metadata(s._owner_scoped_knowledge_base_id(owner, mapping['knowledgeBaseId']),
                mapping['knowledgeItemId'], metadata_patch={'edited': True}, actor_agent_id=lease.agent_id)
    ''', config_text=TEST_MODEL_CONFIG)


    _run(tmp_path / 'source-case', _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-identity.json').read_text())['agentId']
        with offline_migration_profile():
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            new = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='SYNTHETIC_ADDITION', title='New synthetic', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, new['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True,
                knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']),
                knowledge_content='SYNTHETIC_ADDITION')
            new2 = s.collect_source_to_inbox('agent', old, source_type='manual_user_entry',
                original_content='SYNTHETIC_ADDITION_2', title='Another synthetic', actor_agent_id=old)
            s.review_owner_inbox_source('agent', old, new2['inboxSourceId'], decision='accepted',
                reviewed_by_agent_id=old, ingest_on_accept=True,
                knowledge_base_id=s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId']),
                knowledge_content='SYNTHETIC_ADDITION_2')
            workspace = root.parent / 'legacy-workspace'
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, '        partial = ' + repr(partial) + '\n' + _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid='increment-one'):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            if partial != 'none':
                original_import = migration._import_one
                observed = []
                def interrupt_after_first(*args, **kwargs):
                    if partial in ('recoverable', 'edited'):
                        observed.append(original_import(*args, **kwargs)[0])
                    raise RuntimeError('lost after one import')
                original_immutable = migration._immutable
                def interrupt_before_intent(path, value):
                    if path.name.endswith('.intent.json'):
                        raise RuntimeError('lost before intent')
                    return original_immutable(path, value)
                if partial == 'no_intent':
                    migration._immutable = interrupt_before_intent
                else:
                    migration._import_one = interrupt_after_first
                try:
                    sync()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('interruption not observed')
                migration._import_one = original_import
                migration._immutable = original_immutable
                owner = s._require_owner_context('agent', lease.agent_id)
                if partial == 'recoverable':
                    result = sync()
                    assert result['reused'] and len(result['mappings']) == 2
                    assert len(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')) == 3
                    assert sync('different-id')['mappings'] == []
                elif partial == 'edited':
                    mapping = observed[0]
                    s.update_knowledge_item_metadata(s._owner_scoped_knowledge_base_id(owner, mapping['knowledgeBaseId']),
                        mapping['knowledgeItemId'], metadata_patch={'edited_after_interrupt': True}, actor_agent_id=lease.agent_id)
                    fails('knowledge_sync_outcome_unknown', sync)
                    fails('knowledge_sync_prior_outcome_unknown', lambda: sync('different-id'))
                    assert len(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')) == 2
                else:
                    fails('knowledge_sync_outcome_unknown', sync)
                    fails('knowledge_sync_prior_outcome_unknown', lambda: sync('different-id'))
                    assert len(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')) == 1
                    if partial == 'unknown':
                        folder = root / 'knowledge_migrations'
                        plan = json.loads((folder / 'sync_operations' / (migration._digest('increment-one') + '.plan.json')).read_bytes())
                        item_dir = folder / 'sync_items' / migration._digest('increment-one')
                        progress = {'schemaVersion': 1, 'planSha256': migration._digest(plan), 'nextIndex': 0, 'phase': 'ready'}
                        (item_dir / 'progress.json').write_text(json.dumps(progress))
                        terminal = {'schemaVersion': 1, 'planSha256': migration._digest(plan), 'completedCount': 0,
                            'skippedSourceKnowledgeItemIds': plan['sourceKnowledgeItemIds']}
                        (item_dir / 'terminal.json').write_text(json.dumps(terminal))
                        receipt = {'planSha256': migration._digest(plan), 'mappings': [],
                            'skippedSourceKnowledgeItemIds': plan['sourceKnowledgeItemIds']}
                        receipt_path = folder / 'sync_operations' / (migration._digest('increment-one') + '.complete.json')
                        receipt_path.write_text(json.dumps(receipt))
                        fails('knowledge_sync_receipt_invalid', sync)
                        intent = item_dir / (migration._digest(plan['sourceKnowledgeItemIds'][0]) + '.intent.json')
                        assert intent.exists() and intent.with_name(intent.name + '.lock').exists()
                        intent.unlink()
                        # Deleting only the intent still leaves its durable lock trace.
                        fails('knowledge_sync_receipt_invalid', sync)
                sys.exit(0)
            result = sync()
            assert len(result['mappings']) == 2 and result['conflictCount'] == 1
            assert result['pendingCount'] == 0 and not result['readyForCutover']
            again = sync()
            assert again['reused'] and again['mappings'] == result['mappings']
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 3
            assert any(item.get('metadata') == {'edited': True} for item in items)
            # A different operation never resurrects or imports this root twice.
            another = sync('increment-two')
            assert another['mappings'] == [] and another['conflictCount'] == 1
            assert len(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')) == 3
            original = migration._immutable
            def lost_completion(path, value):
                if path.name.endswith('.complete.json'):
                    raise RuntimeError('simulated interruption')
                return original(path, value)
            migration._immutable = lost_completion
            try:
                sync('interrupted')
            except RuntimeError:
                pass
            else:
                raise AssertionError('interruption not observed')
            migration._immutable = original
            assert sync('interrupted')['reused']
            assert sync('different-id')['mappings'] == []
    ''', config_text=TEST_MODEL_CONFIG)


def test_offline_revision_preserves_target_fields_and_confirms_lost_receipt(tmp_path):
    _create_isolated_source(tmp_path)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        with offline_migration_profile() as lease:
            run(lease)
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path / 'source-case', _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-identity.json').read_text())['agentId']
        with offline_migration_profile():
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            item = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')[0]
            scoped = s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId'])
            proposal = s.create_refinement_proposal(scoped, source_artifact_ids=item['sourceArtifactIds'],
                proposed_by_agent_id=old, title='Revised synthetic', content='SYNTHETIC_REVISED',
                supersedes_knowledge_item_id=item['knowledgeItemId'], expected_content_sha256=item['contentSha256'],
                revision_reason='synthetic source update')
            s.review_refinement_proposal(scoped, proposal['proposalId'], status='applied', reviewed_by_agent_id=old)
            workspace = root.parent / 'legacy-workspace'
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime import migration_knowledge_sync as sync_module
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_module.sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            owner = s._require_owner_context('agent', lease.agent_id)
            proposals = s._proposals_path_for_owner(owner)
            saved = proposals.read_bytes() if proposals.exists() else None
            for corrupt, error in ((b'{broken\n', 'invalid_source_json'),
                    (b'{"proposalId":"x"}\n{"proposalId":"x"}\n', 'knowledge_duplicate_source_id')):
                proposals.write_bytes(corrupt)
                before = (contents(s._knowledge_root_for_owner(owner)), contents(root / 'knowledge_migrations'))
                fails(error, lambda: sync('corrupt-proposals'))
                assert (contents(s._knowledge_root_for_owner(owner)), contents(root / 'knowledge_migrations')) == before
                assert not (root / 'knowledge_migrations/sync_operations').exists()
            if saved is None:
                proposals.unlink()
            else:
                proposals.write_bytes(saved)
            original = sync_module._apply_revision
            def lose_ack(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError('lost receipt')
            sync_module._apply_revision = lose_ack
            try:
                sync('revision-one')
            except RuntimeError:
                pass
            else:
                raise AssertionError('interruption not observed')
            sync_module._apply_revision = original
            recovered = sync('revision-one')
            assert recovered['reused'] and len(recovered['mappings']) == 1
            assert recovered['conflictCount'] == 0
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 2
            latest = next(row for row in items if row['knowledgeItemId'] == recovered['mappings'][0]['knowledgeItemId'])
            assert latest['content'] == 'SYNTHETIC_REVISED' and latest['confidence'] == 0.75
            assert sync('revision-two')['mappings'] == []
            assert sync('revision-three')['conflictCount'] == 0
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path / 'source-case', _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-identity.json').read_text())['agentId']
        with offline_migration_profile():
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            item = max(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId'), key=lambda row: row['revision'])
            scoped = s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId'])
            proposal = s.create_refinement_proposal(scoped, source_artifact_ids=item['sourceArtifactIds'],
                proposed_by_agent_id=old, title='Revised again', content='SYNTHETIC_REVISED_AGAIN',
                supersedes_knowledge_item_id=item['knowledgeItemId'], expected_content_sha256=item['contentSha256'],
                revision_reason='another source update')
            s.review_refinement_proposal(scoped, proposal['proposalId'], status='applied', reviewed_by_agent_id=old)
            workspace = root.parent / 'legacy-workspace'
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            def sync(mid):
                return sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                    baseline_migration_id='workspace-bound', sync_id=mid)
            result = sync('revision-four')
            assert len(result['mappings']) == 1 and result['conflictCount'] == 0
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 3
            latest = next(row for row in items if row['knowledgeItemId'] == result['mappings'][0]['knowledgeItemId'])
            assert latest['content'] == 'SYNTHETIC_REVISED_AGAIN' and latest['confidence'] == 0.75
            assert sync('revision-five')['conflictCount'] == 0
            s.update_knowledge_item_metadata(s._owner_scoped_knowledge_base_id(owner, latest['knowledgeBaseId']),
                latest['knowledgeItemId'], metadata_patch={'local': 'user change'}, actor_agent_id=lease.agent_id)
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path / 'source-case', _ISOLATED_IMPORTS + r'''
        old = json.loads((root.parent / 'source-identity.json').read_text())['agentId']
        with offline_migration_profile():
            owner = s._require_owner_context('agent', old)
            base = s._knowledge_bases_for_owner(owner)[0]
            item = max(migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId'), key=lambda row: row['revision'])
            scoped = s._owner_scoped_knowledge_base_id(owner, base['knowledgeBaseId'])
            proposal = s.create_refinement_proposal(scoped, source_artifact_ids=item['sourceArtifactIds'],
                proposed_by_agent_id=old, title='Later source change', content='SYNTHETIC_LATER',
                supersedes_knowledge_item_id=item['knowledgeItemId'], expected_content_sha256=item['contentSha256'],
                revision_reason='later source update')
            s.review_refinement_proposal(scoped, proposal['proposalId'], status='applied', reviewed_by_agent_id=old)
            workspace = root.parent / 'legacy-workspace'
            shutil.copytree(s._knowledge_root_for_owner(owner), workspace / 'agents' / old / 'knowledge', dirs_exist_ok=True)
            registry = workspace / 'knowledge/sources/registry'
            shutil.copyfile(s._central_source_registry_path(), registry / 'source_registry.jsonl')
            shutil.copyfile(s._central_owner_refs_path(), registry / 'owner_refs.jsonl')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, _ISOLATED_SNAPSHOTS + r'''
        from core.assistant_runtime.migration_knowledge_sync import sync_private_knowledge
        with offline_migration_profile() as lease:
            result = sync_private_knowledge(lease, resolved, central=central, owner_refs=refs,
                baseline_migration_id='workspace-bound', sync_id='revision-after-local-edit')
            assert result['mappings'] == [] and result['conflictCount'] > 0
            owner = s._require_owner_context('agent', lease.agent_id)
            items = migration._target_rows(s, owner, s._items_path_for_owner, 'knowledgeItemId')
            assert len(items) == 3
            assert any(row.get('metadata') == {'local': 'user change'} for row in items)
            assert all(row.get('content') != 'SYNTHETIC_LATER' for row in items)
    ''', config_text=TEST_MODEL_CONFIG)
