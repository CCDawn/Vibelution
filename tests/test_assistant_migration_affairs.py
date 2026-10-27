"""Synthetic offline copies into the real native personal-affairs ledger."""
from __future__ import annotations

import json

import pytest

from core.assistant_runtime.migration_affairs import _parse_rows
from core.assistant_runtime.migration_io import MigrationIOError
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def item(item_id="affair-one", **changes):
    return {"schemaVersion": 1, "itemId": item_id, "kind": "todo", "title": "Synthetic task",
            "note": "Synthetic private note", "status": "open", "dueAt": "2025-02-03T00:00:00Z",
            "createdAt": "2025-02-01T00:00:00Z", "updatedAt": "2025-02-01T00:00:00Z",
            "completedAt": "", "sourceTurnId": "legacy-turn", **changes}


def encode(rows):
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


@pytest.mark.parametrize("raw,code", [
    (b"not-json\n", "invalid_source_json"), (b"[]\n", "affairs_row_invalid"),
    (encode([item(), item()]), "affairs_duplicate_item_id"),
    (encode([item(status="deleted")]), "affairs_row_invalid"),
    (encode([item(deleted=True)]), "affairs_row_invalid"),
    (b"\n" * 2049, "affairs_row_limit"),
    (b"x" * (4 * 1024 * 1024 + 1), "affairs_byte_limit"),
    (encode([item(title="SECRET", dueAt="SECRET")]), "affairs_row_invalid"),
], ids=["malformed", "nonobject", "duplicate-id", "unsupported-status", "unknown-field",
        "too-many-lines", "too-many-bytes", "invalid-date"])
def test_strict_bounded_rows_reject_without_content(raw, code):
    with pytest.raises(MigrationIOError) as caught:
        _parse_rows(raw)
    assert str(caught.value) == code
    assert "SECRET" not in str(caught.value)


def test_real_native_import_receipt_crash_recovery_and_conflicts(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os, sys
        from dataclasses import replace
        from pathlib import Path
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('migration must not contact a provider')
        sys.addaudithook(no_network)
        from core.assistant_runtime import migration_affairs as affairs, native
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError, read_stable_file
        from core.web.services import personal_affairs_service, agent_directory_service as directory
        from tools.personal_affairs_tools import personal_affairs_tool
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        # Provision only synthetic native target data, then close it before
        # the offline owner obtains the same OS lock used by a resident host.
        identity = native.bootstrap(root)['assistant']
        assert native.shutdown()['closed']
        row = {'schemaVersion': 1, 'itemId': 'affair-one', 'kind': 'todo', 'title': 'Synthetic task',
            'note': 'PRIVATE_NOTE', 'status': 'open', 'dueAt': '2025-02-03T00:00:00Z',
            'createdAt': '2025-02-01T00:00:00Z', 'updatedAt': '2025-02-01T00:00:00Z',
            'completedAt': '', 'sourceTurnId': 'legacy-turn'}
        scope = {'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'}
        def raw(rows):
            return b''.join(json.dumps(r).encode() + b'\n' for r in rows)
        def run(lease, rows, mid='import-one', **kw):
            body = raw(rows)
            return affairs.import_affairs(lease, body, source_scope=scope,
                source_sha256=hashlib.sha256(body).hexdigest(), migration_id=mid, **kw)
        def fails(code, call):
            try:
                call()
            except MigrationIOError as error:
                assert str(error) == code, str(error)
            else:
                raise AssertionError('accepted invalid import: ' + code)
        with offline_migration_profile() as lease:
            assert lease.agent_id == identity['agentId']
            service = personal_affairs_service.get_personal_affairs_service()
            before_agent = native.identity()
            before_policy = directory.get_agent(lease.agent_id)['toolPolicy']
            first = run(lease, [row])
            assert first['importedCount'] == 1 and not first['idempotent']
            assert first['readyForCutover'] is False and first['sourceQuiesced'] is False
            assert 'PRIVATE_NOTE' not in json.dumps(first)
            projection = service.list_items(lease.agent_id)
            actual = [{k: v for k, v in r.items() if k != 'dueState'} for r in projection['items']]
            assert actual == [row], actual
            assert native.identity() == before_agent
            assert directory.get_agent(lease.agent_id)['toolPolicy'] == before_policy
            with directory.active_agent_runtime(lease.agent_id, session_id=lease.session_id, turn_id='read-import'):
                result = json.loads(personal_affairs_tool(action='list', kind=''))
                assert result['ok'] and result['affairs']['items'][0]['itemId'] == row['itemId']
            fails('affairs_profile_lease_required', lambda: run(replace(lease, agent_id='foreign-agent'), [row]))
            assert run(lease, [row])['idempotent']
            service.complete_item(lease.agent_id, item_id=row['itemId'])
            changed = service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl')
            assert run(lease, [row])['idempotent']
            assert service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl') == changed
            fails('affairs_migration_id_conflict', lambda: run(lease, [{**row, 'title': 'other'}]))
            body = raw([row])
            fails('affairs_migration_id_conflict', lambda: affairs.import_affairs(lease, body,
                source_scope={**scope, 'agentId': 'other-old-pa'}, source_sha256=hashlib.sha256(body).hexdigest(),
                migration_id='import-one'))
            fails('affairs_source_hash_mismatch', lambda: affairs.import_affairs(lease, body,
                source_scope=scope, source_sha256='0' * 64, migration_id='bad-hash'))
            fails('affairs_target_item_conflict', lambda: run(lease, [row], 'different-request'))
            # Crash after atomic ledger publish but before the receipt. No
            # injected production hook: fail the real store receipt method.
            second = {**row, 'itemId': 'affair-two', 'status': 'cancelled'}
            original = affairs._write_receipt
            def crash(path, receipt):
                if receipt['published']:
                    raise RuntimeError('synthetic receipt crash')
                original(path, receipt)
            affairs._write_receipt = crash
            try:
                try:
                    run(lease, [second], 'crash-request')
                except RuntimeError as error:
                    assert str(error) == 'synthetic receipt crash'
                else:
                    raise AssertionError('receipt failure not simulated')
            finally:
                affairs._write_receipt = original
            assert run(lease, [second], 'crash-request')['importedCount'] == 0
            assert len(service.list_items(lease.agent_id)['items']) == 2
            # Interrupted import cannot overwrite a user's later edit.
            third = {**row, 'itemId': 'affair-three', 'kind': 'goal'}
            affairs._write_receipt = crash
            try:
                try:
                    run(lease, [third], 'interrupted-edit')
                except RuntimeError:
                    pass
            finally:
                affairs._write_receipt = original
            service.cancel_item(lease.agent_id, item_id=third['itemId'])
            fails('affairs_outcome_unknown', lambda: run(lease, [third], 'interrupted-edit'))
            source = root.parent / 'old' / 'personal-affairs' / 'affairs' / 'items.jsonl'
            source.parent.mkdir(parents=True)
            fourth = {**row, 'itemId': 'affair-four', 'kind': 'schedule', 'status': 'done',
                'completedAt': '2025-02-02T01:00:00Z'}
            source.write_bytes(raw([fourth]))
            snapshot = read_stable_file(source, 4 * 1024 * 1024)
            affairs.import_affairs(lease, snapshot, source_scope=scope, source_sha256=snapshot.sha256,
                migration_id='snapshot-request')
            assert source.read_bytes() == snapshot.raw
            source.write_bytes(raw([{**fourth, 'title': 'changed'}]))
            fails('source_changed', lambda: affairs.import_affairs(lease, snapshot, source_scope=scope,
                source_sha256=snapshot.sha256, migration_id='snapshot-changed'))
            # Same content via a linked source is still rejected on path identity.
            source.write_bytes(snapshot.raw)
            snapshot = read_stable_file(source, 4 * 1024 * 1024)
            source_alias = source.with_name('linked.jsonl')
            os.link(source, source_alias)
            try:
                fails('source_type_or_link_invalid', lambda: affairs.import_affairs(lease, snapshot,
                    source_scope=scope, source_sha256=snapshot.sha256, migration_id='linked-source'))
            finally:
                source_alias.unlink()
            # The receipt never embeds titles/notes or a second item ledger.
            receipts = list((root / 'affairs_migrations').glob('*.json'))
            assert len(receipts) == 4
            assert all('PRIVATE_NOTE' not in p.read_text() and 'Synthetic task' not in p.read_text() for p in receipts)
            saved_lease = lease
        fails('affairs_profile_lease_required', lambda: run(saved_lease, [row]))
    ''', config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, r'''
        import hashlib, json, sys
        from core.assistant_runtime.migration_affairs import import_affairs
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import agent_directory_service as directory
        from tools.personal_affairs_tools import personal_affairs_tool
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('migration restart must not contact a provider')
        sys.addaudithook(no_network)
        row = {'schemaVersion': 1, 'itemId': 'affair-one', 'kind': 'todo', 'title': 'Synthetic task',
            'note': 'PRIVATE_NOTE', 'status': 'open', 'dueAt': '2025-02-03T00:00:00Z',
            'createdAt': '2025-02-01T00:00:00Z', 'updatedAt': '2025-02-01T00:00:00Z',
            'completedAt': '', 'sourceTurnId': 'legacy-turn'}
        body = json.dumps(row).encode() + b'\n'
        with offline_migration_profile() as lease:
            result = import_affairs(lease, body,
                source_scope={'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'},
                source_sha256=hashlib.sha256(body).hexdigest(), migration_id='import-one')
            assert result['idempotent'] and result['importedCount'] == 0
            with directory.active_agent_runtime(lease.agent_id, session_id=lease.session_id, turn_id='restart-read'):
                rows = json.loads(personal_affairs_tool(action='list', kind=''))['affairs']['items']
                assert {r['itemId']: r['status'] for r in rows} == {
                    'affair-one': 'done', 'affair-two': 'cancelled',
                    'affair-three': 'cancelled', 'affair-four': 'done'}
    ''', config_text=TEST_MODEL_CONFIG)


def test_native_ledger_lock_and_capacity_never_drop_existing_items(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, os, sys, threading
        from pathlib import Path
        from core.assistant_runtime import migration_affairs as affairs
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import personal_affairs_service
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('migration must not contact a provider')
        sys.addaudithook(no_network)
        row = {'schemaVersion': 1, 'itemId': 'item-one', 'kind': 'todo', 'title': 'Synthetic task',
            'note': '', 'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        scope = {'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'}
        def run(lease, rows, mid):
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            return affairs.import_affairs(lease, raw, source_scope=scope,
                source_sha256=hashlib.sha256(raw).hexdigest(), migration_id=mid)
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            started, done = threading.Event(), threading.Event()
            errors = []
            def native_edit():
                started.set()
                try:
                    service.complete_item(lease.agent_id, item_id=row['itemId'])
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()
            writer = threading.Thread(target=native_edit)
            original = affairs._write_receipt
            def write_while_native_edit_waits(*args):
                if args[1]['published']:
                    writer.start()
                    assert started.wait(5)
                    assert not done.wait(.1), 'native writer bypassed the shared ledger lock'
                original(*args)
            affairs._write_receipt = write_while_native_edit_waits
            try:
                assert run(lease, [row], 'shared-lock')['importedCount'] == 1
            finally:
                affairs._write_receipt = original
                writer.join(10)
            assert done.is_set() and not errors
            assert service.list_items(lease.agent_id)['items'][0]['status'] == 'done'
            # Native writers and the importer use the same path, and a full
            # ledger must reject additions rather than evict its oldest item.
            full = [{**row, 'itemId': 'item-' + str(i)} for i in range(2048)]
            service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', full)
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            before = ledger.read_bytes()
            try:
                run(lease, [{**row, 'itemId': 'one-too-many'}], 'full-ledger')
            except MigrationIOError as error:
                assert str(error) == 'affairs_target_row_limit'
            else:
                raise AssertionError('full ledger silently evicted data')
            assert ledger.read_bytes() == before
            alias = ledger.with_name('linked-items.jsonl')
            os.link(ledger, alias)
            try:
                try:
                    run(lease, [row], 'linked-target')
                except MigrationIOError as error:
                    assert str(error) == 'source_type_or_link_invalid'
                else:
                    raise AssertionError('linked target accepted')
            finally:
                alias.unlink()
            # A lease cannot be forwarded into another migration thread.
            def foreign_thread():
                try:
                    run(lease, [], 'foreign-thread')
                except MigrationIOError as error:
                    assert str(error) == 'affairs_profile_lease_required'
                else:
                    errors.append('foreign-thread accepted')
            thread = threading.Thread(target=foreign_thread)
            thread.start()
            thread.join(10)
            assert not thread.is_alive() and not errors
    ''', config_text=TEST_MODEL_CONFIG)


def test_pending_request_is_durable_before_ledger_change_and_cannot_be_retargeted(tmp_path):
    _run(tmp_path, r'''
        import hashlib, json, sys
        from core.assistant_runtime import migration_affairs as affairs
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.web.services import personal_affairs_service
        def no_network(event, _args):
            if event == 'socket.connect':
                raise AssertionError('migration must not contact a provider')
        sys.addaudithook(no_network)
        scope = {'projectId': 'old-project', 'instanceId': 'old-instance', 'agentId': 'old-pa'}
        row = {'schemaVersion': 1, 'itemId': 'pending-one', 'kind': 'todo', 'title': 'Synthetic task',
            'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        def run(lease, rows, mid, source_scope=scope):
            raw = b''.join(json.dumps(r).encode() + b'\n' for r in rows)
            return affairs.import_affairs(lease, raw, source_scope=source_scope,
                source_sha256=hashlib.sha256(raw).hexdigest(), migration_id=mid)
        with offline_migration_profile() as lease:
            service = personal_affairs_service.get_personal_affairs_service()
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            original = affairs._write_receipt
            for mode in ('fresh', 'empty', 'unchanged'):
                mid = 'pending-' + mode
                if mode == 'fresh':
                    rows = [row]
                elif mode == 'empty':
                    rows = []
                else:
                    rows = [service.add_item(lease.agent_id, kind='goal', title='Synthetic native item')]
                receipt_path = lease.root / 'affairs_migrations' / (hashlib.sha256(mid.encode()).hexdigest() + '.json')
                original_write = service.store.write_jsonl
                ledger_written = []
                def require_intent_before_ledger_write(*args):
                    assert receipt_path.exists(), 'ledger changed before request identity was persisted'
                    pending = json.loads(receipt_path.read_text())
                    assert pending['published'] is False and pending['migrationId'] == mid
                    assert pending['sourceScope'] == scope and pending['targetAgentId'] == lease.agent_id
                    result = original_write(*args)
                    ledger_written.append(True)
                    return result
                def fail_publish(path, receipt):
                    if receipt['published']:
                        # The pending request must already be durable before
                        # any success receipt can be attempted.
                        assert path.exists(), 'request intent was not persisted before ledger publish'
                        assert json.loads(path.read_text()) == {**receipt, 'published': False}
                        current = service.store.read_jsonl(lease.agent_id, 'affairs/items.jsonl')
                        assert all(r in current for r in rows)
                        assert bool(ledger_written) == (mode == 'fresh')
                        raise RuntimeError('synthetic publish crash')
                    original(path, receipt)
                affairs._write_receipt = fail_publish
                service.store.write_jsonl = require_intent_before_ledger_write
                try:
                    try:
                        run(lease, rows, mid)
                    except RuntimeError as error:
                        assert str(error) == 'synthetic publish crash'
                    else:
                        raise AssertionError('publish fault seam was not reached')
                finally:
                    affairs._write_receipt = original
                    service.store.write_jsonl = original_write
                assert json.loads(receipt_path.read_text())['published'] is False
                before = ledger.read_bytes() if ledger.exists() else None
                for changed_rows, changed_scope in (([{**row, 'itemId': 'unrelated-' + mode}], scope),
                        (rows, {**scope, 'agentId': 'different-source-pa'})):
                    try:
                        run(lease, changed_rows, mid, changed_scope)
                    except MigrationIOError as error:
                        assert str(error) == 'affairs_migration_id_conflict'
                    else:
                        raise AssertionError('interrupted request identity changed')
                    assert (ledger.read_bytes() if ledger.exists() else None) == before
                    assert json.loads(receipt_path.read_text())['published'] is False
                # JSON numbers are not receipt state booleans.
                intent = json.loads(receipt_path.read_text())
                receipt_path.write_text(json.dumps({**intent, 'published': 0}))
                try:
                    run(lease, rows, mid)
                except MigrationIOError as error:
                    assert str(error) == 'affairs_migration_id_conflict'
                else:
                    raise AssertionError('numeric receipt state was treated as false')
                receipt_path.write_text(json.dumps(intent))
                recovered = run(lease, rows, mid)
                assert recovered['importedCount'] == 0 and not recovered['idempotent']
                assert json.loads(receipt_path.read_text())['published'] is True
                assert (ledger.read_bytes() if ledger.exists() else None) == before
                assert run(lease, rows, mid)['idempotent']
    ''', config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("role", ["workbench", ""])
def test_ordinary_runtime_cannot_supply_an_affairs_target(tmp_path, role):
    _run(tmp_path, r'''
        import hashlib
        from types import SimpleNamespace
        from core.assistant_runtime.migration_affairs import import_affairs
        from core.assistant_runtime.migration_io import MigrationIOError
        try:
            import_affairs(SimpleNamespace(root='C:/fake', agent_id='fake', check=lambda: None), b'',
                source_scope={'projectId': 'p', 'instanceId': 'i', 'agentId': 'a'},
                source_sha256=hashlib.sha256(b'').hexdigest(), migration_id='fake')
        except MigrationIOError as error:
            assert str(error) == 'affairs_profile_lease_required'
        else:
            raise AssertionError('caller-provided target was trusted')
    ''', role=role)


@pytest.mark.parametrize("mutation", ["remove", "partial-remove", "replace", "edit", "before-write", "unchanged"])
def test_pending_receipt_never_replays_changed_or_missing_rows_after_restart(tmp_path, mutation):
    setup = r'''
        import hashlib, json, os, sys
        from pathlib import Path
        from core.assistant_runtime import migration_affairs as migration
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.assistant_runtime.migration_io import MigrationIOError
        from core.infrastructure.file_lock import cross_process_file_lock
        from core.web.services import personal_affairs_service
        def no_network(event, _args):
            if event == 'socket.connect': raise AssertionError('migration contacted a provider')
        sys.addaudithook(no_network)
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        mutation = json.loads((root.parent / 'mutation.json').read_text())
        row = {'schemaVersion': 1, 'itemId': 'pending-old', 'kind': 'todo', 'title': 'Synthetic task',
            'status': 'open', 'createdAt': '2025-02-01T00:00:00Z'}
        retained = {**row, 'itemId': 'pending-retained'}
        rows = [row, retained] if mutation == 'partial-remove' else [row]
        body = b''.join(json.dumps(item).encode() + b'\n' for item in rows)
        def run(lease):
            return migration.import_affairs(lease, body,
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
            service = personal_affairs_service.get_personal_affairs_service()
            ledger = service.store._path(lease.agent_id, 'affairs/items.jsonl')
            receipt = root / 'affairs_migrations' / (hashlib.sha256(b'pending-restart').hexdigest() + '.json')
            assert json.loads(receipt.read_text())['published'] is False
            with cross_process_file_lock(ledger):
                if mutation == 'remove': ledger.unlink()
                elif mutation == 'replace':
                    service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [{**row, 'itemId': 'user-replacement'}])
                elif mutation == 'edit':
                    service.complete_item(lease.agent_id, item_id=row['itemId'])
                elif mutation == 'partial-remove':
                    service.store.write_jsonl(lease.agent_id, 'affairs/items.jsonl', [retained])
                elif mutation == 'before-write': assert not ledger.exists()
            before = ledger.read_bytes() if ledger.exists() else None
            receipt_before = receipt.read_bytes()
            if mutation == 'unchanged':
                result = run(lease)
                assert result['importedCount'] == 0 and not result['idempotent']
                assert ledger.read_bytes() == before
                assert json.loads(receipt.read_text())['published'] is True
                service.complete_item(lease.agent_id, item_id=row['itemId'])
                before = ledger.read_bytes()
            for _ in range(2):
                if mutation == 'unchanged': assert run(lease)['idempotent']
                else:
                    try: run(lease)
                    except MigrationIOError as error: assert str(error) == 'affairs_outcome_unknown'
                    else: raise AssertionError('pending request replayed or completed after user change')
                assert (ledger.read_bytes() if ledger.exists() else None) == before
                if mutation != 'unchanged': assert receipt.read_bytes() == receipt_before
    ''', config_text=TEST_MODEL_CONFIG)
