"""Bounded legacy episodes imported through the real offline native owner."""
from __future__ import annotations

import json

import pytest

from core.assistant_runtime.migration_episodic import _parse_rows
from core.assistant_runtime.migration_io import MigrationIOError
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def episode(episode_id="episode-old", **changes):
    return {"schemaVersion": 1, "episodeId": episode_id, "eventId": episode_id,
            "agentId": "old-pa", "occurredAt": "2025-02-01T00:00:00Z", "kind": "note",
            "text": "Synthetic private note", "refs": [{"type": "session", "id": "legacy-session"}],
            "validFrom": "2025-02-01T00:00:00Z", "validUntil": "",
            "supersededByEpisodeId": "", **changes}


def encode(rows):
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


@pytest.mark.parametrize("raw,code", [
    (b"not-json\n", "invalid_source_json"),
    (b'{"schemaVersion":1,"schemaVersion":1}\n', "invalid_source_json"),
    (encode([episode(schemaVersion=True)]), "episodic_row_invalid"),
    (encode([episode(agentId="other-agent")]), "episodic_actor_mismatch"),
    (encode([episode(), episode()]), "episodic_duplicate_id"),
    (encode([episode("two", eventId="shared"), episode("one", eventId="shared")]), "episodic_duplicate_id"),
    (encode([episode(kind="arbitrary")]), "episodic_row_invalid"),
    (encode([episode(kind=[])]), "episodic_row_invalid"),
    (encode([episode(refs=[{"type": "turn", "id": "legacy-turn"}])]), "episodic_row_invalid"),
    (encode([episode(refs=[{"type": [], "id": "legacy-turn"}])]), "episodic_row_invalid"),
    (encode([episode(text="PRIVATE", unsafe="PRIVATE")]), "episodic_row_invalid"),
    (encode([episode(supersededByEpisodeId="missing")]), "episodic_succession_invalid"),
    (encode([episode(validUntil="2024-01-01T00:00:00Z")]), "episodic_row_invalid"),
    (encode([episode("one", validUntil="2025-02-02T00:00:00Z", supersededByEpisodeId="two"),
             episode("two", validUntil="2025-02-02T00:00:00Z", supersededByEpisodeId="one")]),
     "episodic_succession_invalid"),
    (b"\n" * 4097, "episodic_row_limit"),
    (b"x" * (4 * 1024 * 1024 + 1), "episodic_byte_limit"),
], ids=["json", "duplicate-key", "schema", "actor", "episode-id", "event-id", "kind", "kind-type", "ref", "ref-type",
        "unknown-field", "dangling-successor", "backwards-time", "cycle", "rows", "bytes"])
def test_strict_rows_fail_closed_without_content(raw, code):
    with pytest.raises(MigrationIOError) as caught:
        _parse_rows(raw, "old-pa")
    assert str(caught.value) == code
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("developer_mode", [False, True])
def test_native_import_preserves_history_restart_and_user_edits(tmp_path, developer_mode):
    config = TEST_MODEL_CONFIG + ('\n[launcher.developer_mode]\nenabled = true\n' if developer_mode else '')
    setup = r'''
        import hashlib, json, os
        from pathlib import Path
        from core.assistant_runtime import migration_episodic as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file
        from core.web.services import agent_directory_service as directory
        from core.web.services.agent_directory import episodic_memory as episodes
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        scope = {'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'}
        row = {'schemaVersion': 1, 'episodeId': 'old-one', 'eventId': 'event-one', 'agentId': 'old-pa',
            'occurredAt': '2025-02-01T00:00:00Z', 'kind': 'preference', 'text': 'PRIVATE_NOTE',
            'refs': [{'type': 'session', 'id': 'legacy-session'}, {'type': 'path', 'id': 'old/file'}],
            'validFrom': '2025-02-01T00:00:00Z', 'validUntil': '2025-02-02T00:00:00Z',
            'supersededByEpisodeId': 'old-two'}
        successor = {**row, 'episodeId': 'old-two', 'eventId': 'event-two', 'text': 'Replacement',
            'validFrom': '2025-02-02T00:00:00Z', 'validUntil': '', 'supersededByEpisodeId': ''}
        def raw(rows):
            return b''.join(json.dumps(r).encode() + b'\n' for r in rows)
        def run(lease, rows, mid='migration-one'):
            body = raw(rows)
            return migration.import_episodic(lease, body, source_scope=scope,
                source_sha256=hashlib.sha256(body).hexdigest(), migration_id=mid)
        def fails(code, call):
            try:
                call()
            except MigrationIOError as error:
                assert str(error) == code, str(error)
            else:
                raise AssertionError('invalid import admitted: ' + code)
    '''
    _run(tmp_path, setup + r'''
        with offline_migration_profile() as lease:
            before = directory.get_agent(lease.agent_id)
            result = run(lease, [row, successor])
            assert result['importedCount'] == 2 and not result['idempotent']
            assert result['sourceQuiesced'] is False and result['readyForCutover'] is False
            assert 'PRIVATE_NOTE' not in json.dumps(result)
            history = episodes.list_episodic_events(lease.agent_id, include_superseded=True)
            expected = [{**r, 'agentId': lease.agent_id} for r in [row, successor]]
            assert sorted(history, key=lambda r: r['episodeId']) == expected
            assert [r['episodeId'] for r in episodes.list_current_episodic_events(lease.agent_id)] == ['old-two']
            assert directory.get_agent(lease.agent_id) == before
            assert run(lease, [row, successor])['idempotent']
            (root.parent / 'episode-identity.json').write_text(json.dumps({'agentId': lease.agent_id}))
            saved = lease
        fails('episodic_profile_lease_required', lambda: run(saved, [row, successor]))
    ''', config_text=config)
    _run(tmp_path, setup + r'''
        with offline_migration_profile() as lease:
            assert json.loads((root.parent / 'episode-identity.json').read_text())['agentId'] == lease.agent_id
            assert run(lease, [row, successor])['idempotent']
            new = episodes.append_episodic_event(lease.agent_id, text='User updated preference')
            episodes.supersede_episodic_event(lease.agent_id, 'old-two', successor_episode_id=new['episodeId'])
            ledger = episodes._episodic_events_path(directory.get_agent(lease.agent_id))
            changed = ledger.read_bytes()
            assert run(lease, [row, successor])['idempotent']
            assert ledger.read_bytes() == changed
            fails('episodic_migration_id_conflict', lambda: run(lease, [], 'migration-one'))
            fails('episodic_target_id_conflict', lambda: run(lease, [row, successor], 'other-request'))
            # An actual native commit succeeds, then receipt publication fails.
            third = {**successor, 'episodeId': 'old-three', 'eventId': 'event-three'}
            original = migration._write_receipt
            def crash(path, receipt):
                if receipt['published']:
                    raise RuntimeError('synthetic publication failure')
                original(path, receipt)
            migration._write_receipt = crash
            try:
                try:
                    run(lease, [third], 'crashed')
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('did not inject crash')
            finally:
                migration._write_receipt = original
            fails('episodic_migration_id_conflict', lambda: run(lease, [], 'crashed'))
            assert run(lease, [third], 'crashed')['importedCount'] == 0
            # A pending request cannot overwrite a user's later native edit.
            pending = {**successor, 'episodeId': 'pending-one', 'eventId': 'pending-event'}
            migration._write_receipt = crash
            try:
                try:
                    run(lease, [pending], 'pending-edit')
                except RuntimeError:
                    pass
            finally:
                migration._write_receipt = original
            episodes.supersede_episodic_event(lease.agent_id, 'pending-one', successor_episode_id=new['episodeId'])
            pending_changed = ledger.read_bytes()
            fails('episodic_outcome_unknown', lambda: run(lease, [pending], 'pending-edit'))
            assert ledger.read_bytes() == pending_changed
            fourth = {**successor, 'episodeId': 'old-four', 'eventId': 'event-four'}
            source = root.parent / 'legacy' / 'episodic_events.jsonl'
            source.parent.mkdir()
            source.write_bytes(raw([fourth]))
            snapshot = read_stable_file(source, 4 * 1024 * 1024)
            migration.import_episodic(lease, snapshot, source_scope=scope,
                source_sha256=snapshot.sha256, migration_id='snapshot')
            source.write_bytes(raw([{**fourth, 'text': 'Changed'}]))
            fails('source_changed', lambda: migration.import_episodic(lease, snapshot,
                source_scope=scope, source_sha256=snapshot.sha256, migration_id='changed-snapshot'))
            assert all('PRIVATE_NOTE' not in p.read_text() for p in (root / 'episodic_migrations').glob('*.json'))
            directory.update_agent_instance(lease.agent_id, memory_policy={'enabled': False})
            disabled = ledger.read_bytes()
            fails('episodic_memory_disabled', lambda: run(lease, [], 'disabled'))
            assert ledger.read_bytes() == disabled
    ''', config_text=config)


def test_caller_cannot_forge_offline_lease(tmp_path):
    _run(tmp_path, r'''
        import hashlib
        from types import SimpleNamespace
        from core.assistant_runtime.migration_episodic import import_episodic
        from core.assistant_runtime.migration_io import MigrationIOError
        try:
            import_episodic(SimpleNamespace(root='C:/fake', agent_id='fake', check=lambda: None), b'',
                source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'a'},
                source_sha256=hashlib.sha256(b'').hexdigest(), migration_id='fake')
        except MigrationIOError as error:
            assert str(error) == 'episodic_profile_lease_required'
        else:
            raise AssertionError('forged lease accepted')
    ''', config_text=TEST_MODEL_CONFIG)


def test_target_corruption_limits_and_noncanonical_policy_are_untouched(tmp_path):
    _run(tmp_path, r'''
        import hashlib, os
        from pathlib import Path
        from core.assistant_runtime.migration_episodic import import_episodic
        from core.assistant_runtime.migration_profile import offline_migration_profile, OfflineMigrationProfileLease
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import agent_directory_service as directory
        from core.web.services.agent_directory import episodic_memory as episodes
        scope = {'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'}
        def run(lease, mid='invalid-target', **kw):
            return import_episodic(lease, b'', source_scope=scope,
                source_sha256=hashlib.sha256(b'').hexdigest(), migration_id=mid, **kw)
        def fails(code, call):
            try:
                call()
            except MigrationIOError as error:
                assert str(error) == code, str(error)
            else:
                raise AssertionError('invalid target admitted')
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        with offline_migration_profile() as lease:
            forged = OfflineMigrationProfileLease(root, lease.agent_id, lease.session_id, 0)
            fails('episodic_profile_lease_required', lambda: run(forged))
            ledger = episodes._episodic_events_path(directory.get_agent(lease.agent_id))
            ledger.parent.mkdir(parents=True, exist_ok=True)
            for bad, code in [(b'PRIVATE_BAD_JSON\n', 'invalid_source_json'),
                              (b'\n' * 4097, 'episodic_row_limit'),
                              (b'x' * (4 * 1024 * 1024 + 1), 'file_byte_limit')]:
                ledger.write_bytes(bad)
                fails(code, lambda: run(lease))
                assert ledger.read_bytes() == bad
            ledger.unlink()
            # Even an in-root link must not change the native authority path.
            actual = ledger.with_name('another-file.jsonl')
            actual.write_bytes(b'')
            ledger.symlink_to(actual)
            fails('linked_source', lambda: run(lease))
            assert ledger.is_symlink() and actual.read_bytes() == b''
            ledger.unlink()
            actual.unlink()
            original = directory.resolve_memory_policy_for_agent
            directory.resolve_memory_policy_for_agent = lambda agent_id: {
                **original(agent_id), 'episodicEventsPath': 'workspace/agents/other/events/episodic_events.jsonl'}
            try:
                fails('episodic_target_binding_invalid', lambda: run(lease))
            finally:
                directory.resolve_memory_policy_for_agent = original
            assert not list((root / 'episodic_migrations').glob('*.json'))
    ''', config_text=TEST_MODEL_CONFIG)


def test_workspace_routing_change_before_commit_fails_closed(tmp_path):
    _run(tmp_path, r'''
        import hashlib, os
        from pathlib import Path
        import json
        from core.assistant_runtime import migration_episodic as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import agent_directory_service as directory
        from core.web.services.agent_directory import episodic_memory as episodes
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        with offline_migration_profile() as lease:
            actual = episodes._episodic_events_path(directory.get_agent(lease.agent_id))
            before = actual.read_bytes() if actual.exists() else None
            row = {'schemaVersion': 1, 'episodeId': 'routing-old', 'eventId': 'routing-event', 'agentId': 'old-pa',
                'occurredAt': '2025-02-01T00:00:00Z', 'kind': 'note', 'text': 'Synthetic', 'refs': [],
                'validFrom': '2025-02-01T00:00:00Z', 'validUntil': '', 'supersededByEpisodeId': ''}
            body = json.dumps(row).encode() + b'\n'
            original = migration._write_receipt
            config_path = Path(directory.CONFIG_PATH)
            config_before = config_path.read_bytes()
            def change_route(path, receipt):
                original(path, receipt)
                if not receipt['published']:
                    config_path.write_bytes(config_before.replace(b'enabled = true', b'enabled = false'))
            migration._write_receipt = change_route
            try:
                migration.import_episodic(lease, body, source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'},
                    source_sha256=hashlib.sha256(body).hexdigest(), migration_id='routing-change')
            except MigrationIOError as error:
                assert str(error) == 'episodic_workspace_changed'
            else:
                raise AssertionError('workspace routing changed during import')
            finally:
                migration._write_receipt = original
                config_path.write_bytes(config_before)
            assert (actual.read_bytes() if actual.exists() else None) == before
            receipts = list((root / 'episodic_migrations').glob('*.json'))
            assert len(receipts) == 1 and json.loads(receipts[0].read_text())['published'] is False
    ''', config_text=TEST_MODEL_CONFIG + '\n[launcher.developer_mode]\nenabled = true\n')


def test_ledger_published_before_receipt_recovers_after_abrupt_process_exit(tmp_path):
    setup = r'''
        import hashlib, json, os
        from core.assistant_runtime import migration_episodic as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services.agent_directory import episodic_memory as episodes
        row = {'schemaVersion': 1, 'episodeId': 'crash-old', 'eventId': 'crash-event', 'agentId': 'old-pa',
            'occurredAt': '2025-02-01T00:00:00Z', 'kind': 'note', 'text': 'Synthetic', 'refs': [],
            'validFrom': '2025-02-01T00:00:00Z', 'validUntil': '', 'supersededByEpisodeId': ''}
        body = json.dumps(row).encode() + b'\n'
        def run(lease):
            return migration.import_episodic(lease, body,
                source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'},
                source_sha256=hashlib.sha256(body).hexdigest(), migration_id='actual-process-crash')
    '''
    _run(tmp_path, setup + r'''
        original = migration._write_receipt
        def abrupt_exit(path, receipt):
            if receipt['published']:
                # Cut the actual process after native ledger atomic commit,
                # without context cleanup or writing the completion receipt.
                os._exit(0)
            original(path, receipt)
        migration._write_receipt = abrupt_exit
        with offline_migration_profile() as lease:
            run(lease)
            raise AssertionError('process did not exit between ledger and receipt')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, setup + r'''
        with offline_migration_profile() as lease:
            history = episodes.list_episodic_events(lease.agent_id, include_superseded=True)
            assert history == [{**row, 'agentId': lease.agent_id}]
            result = run(lease)
            assert result['importedCount'] == 0 and not result['idempotent']
            assert run(lease)['idempotent']
            assert episodes.list_episodic_events(lease.agent_id, include_superseded=True) == history
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("mutation", ["remove", "partial-remove", "replace", "edit", "before-write", "unchanged"])
def test_pending_receipt_never_replays_changed_or_missing_rows_after_restart(tmp_path, mutation):
    setup = r'''
        import hashlib, json, os, sys
        from pathlib import Path
        from core.assistant_runtime import migration_episodic as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.infrastructure.file_lock import cross_process_file_lock
        from core.web.services.agent_directory import episodic_memory as episodes
        def no_network(event, _args):
            if event == 'socket.connect': raise AssertionError('migration contacted a provider')
        sys.addaudithook(no_network)
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        mutation = json.loads((root.parent / 'mutation.json').read_text())
        row = {'schemaVersion': 1, 'episodeId': 'pending-old', 'eventId': 'pending-event', 'agentId': 'old-pa',
            'occurredAt': '2025-02-01T00:00:00Z', 'kind': 'note', 'text': 'Synthetic', 'refs': [],
            'validFrom': '2025-02-01T00:00:00Z', 'validUntil': '', 'supersededByEpisodeId': ''}
        retained = {**row, 'episodeId': 'pending-retained', 'eventId': 'retained-event'}
        rows = [row, retained] if mutation == 'partial-remove' else [row]
        body = b''.join(json.dumps(item).encode() + b'\n' for item in rows)
        def run(lease):
            return migration.import_episodic(lease, body,
                source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'old-pa'},
                source_sha256=hashlib.sha256(body).hexdigest(), migration_id='pending-restart')
    '''
    (tmp_path / "mutation.json").write_text(json.dumps(mutation), encoding="utf-8")
    _run(tmp_path, setup + r'''
        original = migration._write_receipt
        def abrupt_exit(path, receipt):
            if not receipt['published']: original(path, receipt)
            if receipt['published'] or mutation == 'before-write': os._exit(0)
        migration._write_receipt = abrupt_exit
        with offline_migration_profile() as lease:
            run(lease)
            raise AssertionError('did not exit between intent and receipt publication')
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, setup + r'''
        with offline_migration_profile() as lease:
            from core.web.services import agent_directory_service as directory
            ledger = episodes._episodic_events_path(directory.get_agent(lease.agent_id))
            receipt = root / 'episodic_migrations' / (hashlib.sha256(b'pending-restart').hexdigest() + '.json')
            assert json.loads(receipt.read_text())['published'] is False
            if mutation == 'remove':
                with cross_process_file_lock(ledger): ledger.unlink()
            elif mutation == 'replace':
                with episodes.episodic_transaction(lease.agent_id) as transaction:
                    transaction.events.clear()
                    transaction.append(text='Synthetic user replacement')
            elif mutation == 'edit':
                episodes.supersede_episodic_event(lease.agent_id, row['episodeId'])
            elif mutation == 'partial-remove':
                with episodes.episodic_transaction(lease.agent_id) as transaction:
                    transaction.events[:] = [item for item in transaction.events if item['episodeId'] != row['episodeId']]
                    transaction._dirty = True
            elif mutation == 'before-write': assert not ledger.exists()
            before = ledger.read_bytes() if ledger.exists() else None
            receipt_before = receipt.read_bytes()
            if mutation == 'unchanged':
                result = run(lease)
                assert result['importedCount'] == 0 and not result['idempotent']
                assert ledger.read_bytes() == before
                assert json.loads(receipt.read_text())['published'] is True
                episodes.supersede_episodic_event(lease.agent_id, row['episodeId'])
                before = ledger.read_bytes()
            for _ in range(2):
                if mutation == 'unchanged': assert run(lease)['idempotent']
                else:
                    try: run(lease)
                    except MigrationIOError as error: assert str(error) == 'episodic_outcome_unknown'
                    else: raise AssertionError('pending request replayed or completed after user change')
                assert (ledger.read_bytes() if ledger.exists() else None) == before
                if mutation != 'unchanged': assert receipt.read_bytes() == receipt_before
    ''', config_text=TEST_MODEL_CONFIG)
